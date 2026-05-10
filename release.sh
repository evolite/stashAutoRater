#!/bin/bash

# Release script for stashAutoRater plugin
# Usage: ./release.sh [bug|minor|major]
#   bug:    Increment patch version (1.0.0 -> 1.0.1)
#   minor:  Increment minor version (1.0.0 -> 1.1.0)
#   major:  Increment major version (1.0.0 -> 2.0.0)

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
PLUGIN_DIR="$SCRIPT_DIR"
PLUGIN_NAME="stashAutoRater"
ZIP_FILE="$SCRIPT_DIR/$PLUGIN_NAME.zip"
YML_PATH="$SCRIPT_DIR/stashAutoRater.yml"
PAGES_DIR="/home/evotech/Projects/pages"
PAGES_INDEX="$PAGES_DIR/index.yml"

source "$(dirname "$SCRIPT_DIR")/.env"
CODEBERG_API="https://codeberg.org/api/v1"
CODEBERG_OWNER="surging9143"
CODEBERG_REPO="stashAutoRater"

echo -e "${CYAN}=== Stash Auto Rater Release Script ===${NC}"
echo ""

if ! command -v curl &> /dev/null; then
    echo -e "${RED}Error: curl is not installed.${NC}" >&2; exit 1
fi
if ! command -v 7z &> /dev/null && ! command -v zip &> /dev/null; then
    echo -e "${RED}Error: zip or 7z is required.${NC}" >&2; exit 1
fi

# Step 1: Bump version in stashAutoRater.yml
VERSION_BUMP="$1"
CURRENT_VERSION=$(grep -oP 'version:\s*\K\d+\.\d+\.\d+' "$YML_PATH")
if [[ -z "$CURRENT_VERSION" ]]; then
    echo -e "${RED}Error: Could not parse version from $YML_PATH${NC}" >&2; exit 1
fi

if [[ -n "$VERSION_BUMP" ]]; then
    echo -e "${YELLOW}Step 1: Bumping version ($VERSION_BUMP)...${NC}"
    [[ ! "$VERSION_BUMP" =~ ^(bug|minor|major)$ ]] && {
        echo -e "${RED}Error: Use 'bug', 'minor', or 'major'.${NC}" >&2; exit 1
    }
    IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
    case "$VERSION_BUMP" in
        bug)   PATCH=$((PATCH + 1)) ;;
        minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
        major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
    esac
    NEW_VERSION="$MAJOR.$MINOR.$PATCH"
    sed -i "s/version: [0-9]\+\.[0-9]\+\.[0-9]\+/version: $NEW_VERSION/" "$YML_PATH"
    echo -e "${GREEN}Version: $CURRENT_VERSION -> $NEW_VERSION${NC}"
    VERSION="$NEW_VERSION"
else
    VERSION="$CURRENT_VERSION"
    echo -e "${GRAY}Step 1: Using current version $VERSION (no bump requested)${NC}"
fi
echo ""

# Step 2: Create zip from parent dir so plugin files are inside StashAutoRate/
echo -e "${YELLOW}Step 2: Creating zip...${NC}"
rm -f "$ZIP_FILE"
cd "$PARENT_DIR"
if command -v zip &> /dev/null; then
    zip -r "$ZIP_FILE" "StashAutoRate/" -q -x "*.git*" -x "*.zip" -x "*/release.sh" -x "*/.gitignore" -x "*/__pycache__/*" -x "*.pyc"
else
    7z a -tzip "$ZIP_FILE" "StashAutoRate/" -xr'!.git' -xr'!*.zip' -xr'!release.sh' -xr'!.gitignore' -xr'!__pycache__' -xr'!*.pyc' -y > /dev/null
fi
echo -e "${GREEN}Created $ZIP_FILE${NC}"
echo ""

# Step 3: Compute SHA256
echo -e "${YELLOW}Step 3: Computing SHA256...${NC}"
HASH=$(sha256sum "$ZIP_FILE" | cut -d' ' -f1)
echo -e "${GREEN}Hash: $HASH${NC}"
echo ""

# Step 4: Commit and push plugin code
echo -e "${YELLOW}Step 4: Committing and pushing plugin code...${NC}"
cd "$PLUGIN_DIR"
git add stashAutoRater.yml
if ! git diff --staged --quiet; then
    git commit -m "Bump version to $VERSION and Release v$VERSION"
fi
git push origin HEAD
echo -e "${GREEN}Plugin pushed to Codeberg.${NC}"
echo ""

# Step 5: Create Codeberg release
echo -e "${YELLOW}Step 5: Creating Codeberg release v$VERSION...${NC}"

# Delete existing release if present
EXISTING=$(curl -sL \
    -H "Authorization: token $CODEBERG_TOKEN" \
    "$CODEBERG_API/repos/$CODEBERG_OWNER/$CODEBERG_REPO/releases/tags/v$VERSION")
EXISTING_ID=$(echo "$EXISTING" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('id',''))" 2>/dev/null || echo "")
if [[ -n "$EXISTING_ID" ]]; then
    echo -e "${GRAY}Deleting existing release $EXISTING_ID...${NC}"
    curl -sL -X DELETE \
        -H "Authorization: token $CODEBERG_TOKEN" \
        "$CODEBERG_API/repos/$CODEBERG_OWNER/$CODEBERG_REPO/releases/$EXISTING_ID" > /dev/null
fi

RELEASE_RESPONSE=$(curl -sL -X POST \
    -H "Authorization: token $CODEBERG_TOKEN" \
    -H "Content-Type: application/json" \
    "$CODEBERG_API/repos/$CODEBERG_OWNER/$CODEBERG_REPO/releases" \
    -d "{\"tag_name\":\"v$VERSION\",\"name\":\"v$VERSION\",\"body\":\"Release v$VERSION\",\"target_commitish\":\"main\",\"draft\":false,\"prerelease\":false}")
RELEASE_ID=$(echo "$RELEASE_RESPONSE" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('id',''))" 2>/dev/null || echo "")

if [[ -z "$RELEASE_ID" ]]; then
    echo -e "${RED}Error: Failed to create release.${NC}" >&2
    echo "$RELEASE_RESPONSE" >&2; exit 1
fi
echo -e "${GREEN}Release created (ID: $RELEASE_ID)${NC}"
echo ""

# Step 6: Upload zip asset
echo -e "${YELLOW}Step 6: Uploading $PLUGIN_NAME.zip...${NC}"
UPLOAD=$(curl -sL -X POST \
    -H "Authorization: token $CODEBERG_TOKEN" \
    -H "Content-Type: application/octet-stream" \
    "$CODEBERG_API/repos/$CODEBERG_OWNER/$CODEBERG_REPO/releases/$RELEASE_ID/assets?name=$PLUGIN_NAME.zip" \
    --data-binary "@$ZIP_FILE")
ASSET_ID=$(echo "$UPLOAD" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('id',''))" 2>/dev/null || echo "")
[[ -z "$ASSET_ID" ]] && echo -e "${RED}Warning: asset upload may have failed${NC}" || echo -e "${GREEN}Asset uploaded (ID: $ASSET_ID)${NC}"
echo ""

# Step 7: Update pages index.yml
echo -e "${YELLOW}Step 7: Updating pages index.yml...${NC}"
if [[ ! -d "$PAGES_DIR" ]]; then
    echo -e "${YELLOW}Warning: Pages repo not found at $PAGES_DIR — skipping.${NC}"
else
    CURRENT_DATE=$(date +"%Y-%m-%d %H:%M:%S")
    DOWNLOAD_URL="https://codeberg.org/$CODEBERG_OWNER/$CODEBERG_REPO/releases/download/v$VERSION/$PLUGIN_NAME.zip"

    if grep -q "id: stashAutoRater" "$PAGES_INDEX"; then
        python3 - <<PYEOF
import re, sys

with open("$PAGES_INDEX") as f:
    content = f.read()

content = re.sub(
    r'(- id: stashAutoRater\b.*?version: )\S+',
    r'\g<1>$VERSION',
    content, flags=re.DOTALL
)
content = re.sub(
    r'(- id: stashAutoRater\b.*?date: ")[^"]+(")',
    r'\g<1>$CURRENT_DATE\g<2>',
    content, flags=re.DOTALL
)
content = re.sub(
    r'(- id: stashAutoRater\b.*?path: )\S+',
    r'\g<1>$DOWNLOAD_URL',
    content, flags=re.DOTALL
)
content = re.sub(
    r'(- id: stashAutoRater\b.*?sha256: )\S+',
    r'\g<1>$HASH',
    content, flags=re.DOTALL
)

with open("$PAGES_INDEX", "w") as f:
    f.write(content)
PYEOF
    else
        cat >> "$PAGES_INDEX" <<EOF

- id: stashAutoRater
  name: Stash Auto Rater
  metadata:
    description: Sets performer, studio, group, and gallery ratings to the Bayesian average of their rated scenes and images
  version: $VERSION
  date: "$CURRENT_DATE"
  path: $DOWNLOAD_URL
  sha256: $HASH
EOF
    fi

    cd "$PAGES_DIR"
    git add index.yml
    if ! git diff --staged --quiet; then
        git commit -m "Update stashAutoRater to v$VERSION"
        git push origin HEAD
        echo -e "${GREEN}Pages index updated and pushed.${NC}"
    else
        echo -e "${GRAY}Pages index already up to date.${NC}"
    fi
fi
echo ""

echo -e "${CYAN}=== Release Complete ===${NC}"
echo -e "${GREEN}Version:  v$VERSION${NC}"
echo -e "${GREEN}Hash:     $HASH${NC}"
echo -e "${GREEN}Release:  https://codeberg.org/$CODEBERG_OWNER/$CODEBERG_REPO/releases/tag/v$VERSION${NC}"
echo -e "${GREEN}Index:    https://surging9143.codeberg.page/index.yml${NC}"
