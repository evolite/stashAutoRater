import os
import re

version = os.environ['VERSION']
hash_   = os.environ['HASH']
date    = os.environ['DATE']
url     = os.environ['URL']

path = "/tmp/pages/index.yml"
with open(path) as f:
    content = f.read()

entry = (
    "- id: stashAutoRater\n"
    "  name: Stash Auto Rater\n"
    "  metadata:\n"
    "    description: Sets performer, studio, group, and gallery ratings to the Bayesian average of their rated scenes and images\n"
    f"  version: {version}\n"
    f'  date: "{date}"\n'
    f"  path: {url}\n"
    f"  sha256: {hash_}"
)

if "id: stashAutoRater" in content:
    content = re.sub(
        r'- id: stashAutoRater\b.*?(?=\n- |\Z)',
        entry,
        content, flags=re.DOTALL
    )
else:
    content = content.rstrip('\n') + '\n' + entry + '\n'

with open(path, "w") as f:
    f.write(content)
