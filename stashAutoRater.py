import json
import math
import statistics
import sys

from stashapi import log
from stashapi.stashapp import StashInterface

CONFIDENCE = 10
O_BOOST = 0        # additive boost per log(1 + o_count); configurable in Stash plugin settings
PLAY_BOOST = 0     # additive boost per log(1 + total_play_count); configurable
WATCH_BOOST = 0    # additive boost per log(1 + total_watch_hours); configurable
FAVORITE_BOOST = 0 # flat points added when entity is marked as favorite; configurable
TAG_BOOST = 0      # additive boost per log(1 + favorited_tag_hits); configurable

RATE_PERFORMERS = True
RATE_STUDIOS    = True
RATE_GROUPS     = True
RATE_GALLERIES  = True

MAX_GROUP_DEPTH = 4  # levels of sub_groups to include when rating a group

MSG_DONE = "Done."

# --- Hook context ---

FIND_SCENE_CONTEXT = """
query FindScene($id: ID!) {
  findScene(id: $id) {
    performers { id name rating100 o_counter favorite }
    studio     { id name rating100 o_counter favorite }
    groups     { group { id name rating100 o_counter } }
  }
}
"""

FIND_IMAGE_CONTEXT = """
query FindImage($id: ID!) {
  findImage(id: $id) {
    performers { id name rating100 o_counter favorite }
    studio     { id name rating100 o_counter favorite }
    galleries  { id title rating100 scenes { o_counter } }
  }
}
"""

# --- Entity lookups ---

FIND_PERFORMER = """
query FindPerformer($id: ID!) {
  findPerformer(id: $id) { id name rating100 o_counter favorite }
}
"""

FIND_STUDIO = """
query FindStudio($id: ID!) {
  findStudio(id: $id) { id name rating100 o_counter favorite }
}
"""

FIND_GROUP = """
query FindGroup($id: ID!) {
  findGroup(id: $id) { id name rating100 o_counter }
}
"""

FIND_GALLERY = """
query FindGallery($id: ID!) {
  findGallery(id: $id) { id title rating100 scenes { o_counter } }
}
"""

# --- Find all ---

FIND_ALL_PERFORMERS = """
query { findPerformers(filter: {per_page: -1}) {
  performers { id name rating100 o_counter favorite }
} }
"""

FIND_ALL_STUDIOS = """
query { findStudios(filter: {per_page: -1}) {
  studios { id name rating100 o_counter favorite }
} }
"""

FIND_ALL_GROUPS = """
query { findGroups(filter: {per_page: -1}) {
  groups { id name rating100 o_counter }
} }
"""

FIND_ALL_GALLERIES = """
query { findGalleries(filter: {per_page: -1}) {
  galleries { id title rating100 scenes { o_counter } }
} }
"""

# --- Global mean ---

FIND_RATED_SCENES = """
query { findScenes(filter: {per_page: -1},
  scene_filter: {rating100: {value: 0, modifier: GREATER_THAN}}) {
  scenes { rating100 }
} }
"""

FIND_RATED_IMAGES = """
query { findImages(filter: {per_page: -1},
  image_filter: {rating100: {value: 0, modifier: GREATER_THAN}}) {
  images { rating100 }
} }
"""

# --- Content queries: scenes ---

FIND_SCENES = """
query FindScenes($scene_filter: SceneFilterType!) {
  findScenes(filter: {per_page: -1}, scene_filter: $scene_filter) {
    scenes { id rating100 play_count play_duration }
  }
}
"""

FIND_SCENES_WITH_TAGS = """
query FindScenes($scene_filter: SceneFilterType!) {
  findScenes(filter: {per_page: -1}, scene_filter: $scene_filter) {
    scenes { id rating100 play_count play_duration tags { id favorite } }
  }
}
"""

# --- Content queries: images ---

FIND_IMAGES = """
query FindImages($image_filter: ImageFilterType!) {
  findImages(filter: {per_page: -1}, image_filter: $image_filter) {
    images { id rating100 }
  }
}
"""

FIND_IMAGES_WITH_TAGS = """
query FindImages($image_filter: ImageFilterType!) {
  findImages(filter: {per_page: -1}, image_filter: $image_filter) {
    images { id rating100 tags { id favorite } }
  }
}
"""

# --- Group hierarchy ---

FIND_GROUP_SUBGROUPS = """
query FindGroup($id: ID!) {
  findGroup(id: $id) {
    sub_groups { group { id } }
  }
}
"""

FIND_GROUP_PARENTS = """
query FindGroup($id: ID!) {
  findGroup(id: $id) {
    containing_groups { group { id name rating100 o_counter } }
  }
}
"""

# --- Mutations ---

PERFORMER_UPDATE = """
mutation PerformerUpdate($input: PerformerUpdateInput!) {
  performerUpdate(input: $input) { id }
}
"""

STUDIO_UPDATE = """
mutation StudioUpdate($input: StudioUpdateInput!) {
  studioUpdate(input: $input) { id }
}
"""

GROUP_UPDATE = """
mutation GroupUpdate($input: GroupUpdateInput!) {
  groupUpdate(input: $input) { id }
}
"""

GALLERY_UPDATE = """
mutation GalleryUpdate($input: GalleryUpdateInput!) {
  galleryUpdate(input: $input) { id }
}
"""

stash = None


def graphql(query, variables=None):
    return stash.call_GQL(query, variables or {})


def get_global_mean():
    scene_ratings = [s["rating100"] for s in graphql(FIND_RATED_SCENES).get("findScenes", {}).get("scenes", []) if s.get("rating100") is not None]
    image_ratings = [i["rating100"] for i in graphql(FIND_RATED_IMAGES).get("findImages", {}).get("images", []) if i.get("rating100") is not None]
    all_ratings = scene_ratings + image_ratings
    return statistics.mean(all_ratings) if all_ratings else 50.0


def compute_rating(rated, play_sum, watch_sum, tag_hits, o_count, is_favorite, global_mean):
    if not rated:
        return None
    n = len(rated)
    watch_hours = watch_sum / 3600
    bayesian = (CONFIDENCE * global_mean + sum(rated)) / (CONFIDENCE + n)
    boost = (O_BOOST * math.log(1 + o_count)
             + PLAY_BOOST * math.log(1 + play_sum)
             + WATCH_BOOST * math.log(1 + watch_hours)
             + TAG_BOOST * tag_hits)
    if is_favorite:
        boost += FAVORITE_BOOST
    return min(round(bayesian + boost), 100)


def collect_scenes(scene_filter):
    scene_q = FIND_SCENES_WITH_TAGS if TAG_BOOST else FIND_SCENES
    return graphql(scene_q, {"scene_filter": scene_filter}).get("findScenes", {}).get("scenes", [])


def collect_images(image_filter):
    image_q = FIND_IMAGES_WITH_TAGS if TAG_BOOST else FIND_IMAGES
    return graphql(image_q, {"image_filter": image_filter}).get("findImages", {}).get("images", [])


def scene_stats(scenes):
    ratings = [s["rating100"] for s in scenes if s.get("rating100") is not None]
    play_sum = sum(s.get("play_count") or 0 for s in scenes)
    watch_sum = sum(s.get("play_duration") or 0 for s in scenes)
    return ratings, play_sum, watch_sum


def image_stats(images):
    return [i["rating100"] for i in images if i.get("rating100") is not None]


def tag_hits_from(items):
    if not TAG_BOOST:
        return 0
    tag_counts = {}
    for item in items:
        for t in item.get("tags", []):
            if t.get("favorite"):
                tag_counts[t["id"]] = tag_counts.get(t["id"], 0) + 1
    return sum(math.log(1 + c) for c in tag_counts.values())


# --- Performers ---

def get_performer_data(performer_id):
    scenes = collect_scenes({"performers": {"value": [performer_id], "modifier": "INCLUDES_ALL"}})
    images = collect_images({"performers": {"value": [performer_id], "modifier": "INCLUDES_ALL"}})
    s_ratings, play_sum, watch_sum = scene_stats(scenes)
    i_ratings = image_stats(images)
    tag_hits = tag_hits_from(scenes + images)
    return s_ratings + i_ratings, play_sum, watch_sum, tag_hits


def rate_performer(performer, global_mean):
    rated, play_sum, watch_sum, tag_hits = get_performer_data(performer["id"])
    final = compute_rating(rated, play_sum, watch_sum, tag_hits,
                           performer.get("o_counter") or 0,
                           performer.get("favorite", False), global_mean)
    if final is None or final == performer.get("rating100"):
        return
    graphql(PERFORMER_UPDATE, {"input": {"id": performer["id"], "rating100": final}})
    log.info(f"Performer {performer['name']} → {final}/100 (n={len(rated)}, o={performer.get('o_counter') or 0}, plays={play_sum}, watch={watch_sum/3600:.1f}h, tags={tag_hits:.2f})")


def rate_all_performers(global_mean):
    performers = graphql(FIND_ALL_PERFORMERS).get("findPerformers", {}).get("performers", [])
    log.info(f"Rating {len(performers)} performers...")
    for p in performers:
        try:
            rate_performer(p, global_mean)
        except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
            log.error(f"ERROR rating performer {p.get('name', p['id'])}: {e}")


# --- Studios ---

def get_studio_data(studio_id):
    scenes = collect_scenes({"studios": {"value": [studio_id], "modifier": "INCLUDES_ALL"}})
    images = collect_images({"studios": {"value": [studio_id], "modifier": "INCLUDES_ALL"}})
    s_ratings, play_sum, watch_sum = scene_stats(scenes)
    i_ratings = image_stats(images)
    tag_hits = tag_hits_from(scenes + images)
    return s_ratings + i_ratings, play_sum, watch_sum, tag_hits


def rate_studio(studio, global_mean):
    rated, play_sum, watch_sum, tag_hits = get_studio_data(studio["id"])
    final = compute_rating(rated, play_sum, watch_sum, tag_hits,
                           studio.get("o_counter") or 0,
                           studio.get("favorite", False), global_mean)
    if final is None or final == studio.get("rating100"):
        return
    graphql(STUDIO_UPDATE, {"input": {"id": studio["id"], "rating100": final}})
    log.info(f"Studio {studio['name']} → {final}/100 (n={len(rated)}, o={studio.get('o_counter') or 0}, plays={play_sum}, watch={watch_sum/3600:.1f}h, tags={tag_hits:.2f})")


def rate_all_studios(global_mean):
    studios = graphql(FIND_ALL_STUDIOS).get("findStudios", {}).get("studios", [])
    log.info(f"Rating {len(studios)} studios...")
    for s in studios:
        try:
            rate_studio(s, global_mean)
        except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
            log.error(f"ERROR rating studio {s.get('name', s['id'])}: {e}")


# --- Groups ---

def collect_group_scenes_recursive(group_id, remaining, seen=None):
    if seen is None:
        seen = set()
    if group_id in seen:
        return []
    seen.add(group_id)
    scenes = collect_scenes({"groups": {"value": [group_id], "modifier": "INCLUDES_ALL"}})
    if remaining > 0:
        result = graphql(FIND_GROUP_SUBGROUPS, {"id": group_id})
        for assoc in (result.get("findGroup") or {}).get("sub_groups", []):
            sg = assoc.get("group") if isinstance(assoc, dict) and "group" in assoc else assoc
            if sg and sg.get("id"):
                scenes += collect_group_scenes_recursive(sg["id"], remaining - 1, seen)
    return scenes


def rate_group_ancestors(group_id, global_mean, depth=0, seen=None):
    if seen is None:
        seen = set()
    if group_id in seen or depth >= MAX_GROUP_DEPTH:
        return
    seen.add(group_id)
    result = graphql(FIND_GROUP_PARENTS, {"id": group_id})
    for assoc in (result.get("findGroup") or {}).get("containing_groups", []):
        parent = assoc.get("group") if isinstance(assoc, dict) and "group" in assoc else assoc
        if not parent or parent.get("id") in seen:
            continue
        try:
            rate_group(parent, global_mean)
        except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
            log.error(f"ERROR rating group {parent.get('name', parent['id'])}: {e}")
        rate_group_ancestors(parent["id"], global_mean, depth + 1, seen)


def get_group_data(group_id):
    scenes = collect_group_scenes_recursive(group_id, MAX_GROUP_DEPTH)
    s_ratings, play_sum, watch_sum = scene_stats(scenes)
    tag_hits = tag_hits_from(scenes)
    return s_ratings, play_sum, watch_sum, tag_hits


def rate_group(group, global_mean):
    rated, play_sum, watch_sum, tag_hits = get_group_data(group["id"])
    final = compute_rating(rated, play_sum, watch_sum, tag_hits,
                           group.get("o_counter") or 0,
                           group.get("favorite", False), global_mean)
    if final is None or final == group.get("rating100"):
        return
    graphql(GROUP_UPDATE, {"input": {"id": group["id"], "rating100": final}})
    log.info(f"Group {group['name']} → {final}/100 (n={len(rated)}, plays={play_sum}, watch={watch_sum/3600:.1f}h, tags={tag_hits:.2f})")


def rate_all_groups(global_mean):
    groups = graphql(FIND_ALL_GROUPS).get("findGroups", {}).get("groups", [])
    log.info(f"Rating {len(groups)} groups...")
    for g in groups:
        try:
            rate_group(g, global_mean)
        except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
            log.error(f"ERROR rating group {g.get('name', g['id'])}: {e}")


# --- Galleries ---

def get_gallery_data(gallery_id):
    images = collect_images({"galleries": {"value": [gallery_id], "modifier": "INCLUDES_ALL"}})
    i_ratings = image_stats(images)
    tag_hits = tag_hits_from(images)
    return i_ratings, tag_hits


def rate_gallery(gallery, global_mean):
    rated, tag_hits = get_gallery_data(gallery["id"])
    o_count = sum(s.get("o_counter") or 0 for s in gallery.get("scenes", []))
    final = compute_rating(rated, 0, 0, tag_hits, o_count, False, global_mean)
    if final is None or final == gallery.get("rating100"):
        return
    graphql(GALLERY_UPDATE, {"input": {"id": gallery["id"], "rating100": final}})
    log.info(f"Gallery {gallery.get('title') or gallery['id']} → {final}/100 (n={len(rated)}, o={o_count}, tags={tag_hits:.2f})")


def rate_all_galleries(global_mean):
    galleries = graphql(FIND_ALL_GALLERIES).get("findGalleries", {}).get("galleries", [])
    log.info(f"Rating {len(galleries)} galleries...")
    for g in galleries:
        try:
            rate_gallery(g, global_mean)
        except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
            log.error(f"ERROR rating gallery {g.get('title') or g['id']}: {e}")


# --- Hook helpers ---

def _rate_performers_list(performers, global_mean):
    for p in performers:
        try:
            rate_performer(p, global_mean)
        except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
            log.error(f"ERROR rating performer {p.get('name', p['id'])}: {e}")


def _rate_studio(studio, global_mean):
    try:
        rate_studio(studio, global_mean)
    except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
        log.error(f"ERROR rating studio {studio.get('name', studio['id'])}: {e}")


def _rate_groups_list(groups, global_mean):
    for assoc in groups:
        g = assoc.get("group") if isinstance(assoc, dict) and "group" in assoc else assoc
        if not g:
            continue
        try:
            rate_group(g, global_mean)
        except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
            log.error(f"ERROR rating group {g.get('name', g['id'])}: {e}")
        rate_group_ancestors(g["id"], global_mean)


def _rate_galleries_list(galleries, global_mean):
    for gal in galleries:
        try:
            rate_gallery(gal, global_mean)
        except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
            log.error(f"ERROR rating gallery {gal.get('title') or gal['id']}: {e}")


def rate_entities_from_scene(scene_id, global_mean):
    result = graphql(FIND_SCENE_CONTEXT, {"id": scene_id}).get("findScene") or {}
    if RATE_PERFORMERS:
        _rate_performers_list(result.get("performers", []), global_mean)
    if RATE_STUDIOS and result.get("studio"):
        _rate_studio(result["studio"], global_mean)
    if RATE_GROUPS:
        _rate_groups_list(result.get("groups", []), global_mean)


def rate_entities_from_image(image_id, global_mean):
    result = graphql(FIND_IMAGE_CONTEXT, {"id": image_id}).get("findImage") or {}
    if RATE_PERFORMERS:
        _rate_performers_list(result.get("performers", []), global_mean)
    if RATE_STUDIOS and result.get("studio"):
        _rate_studio(result["studio"], global_mean)
    if RATE_GALLERIES:
        _rate_galleries_list(result.get("galleries", []), global_mean)


def parse_boost(raw, name, current):
    if raw in (None, ""):
        return current
    try:
        return float(str(raw).replace(",", "."))
    except ValueError:
        log.warning(f"Invalid {name} value {raw!r}, using default ({current})")
        return current


def parse_bool(raw, current):
    if raw is None:
        return current
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() not in ("false", "0", "no", "")


def _handle_performer_hook(entity_id, global_mean):
    if not RATE_PERFORMERS:
        return
    result = graphql(FIND_PERFORMER, {"id": entity_id}).get("findPerformer")
    if result:
        try:
            rate_performer(result, global_mean)
        except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
            log.error(f"ERROR rating performer {result.get('name', entity_id)}: {e}")


def _handle_studio_hook(entity_id, global_mean):
    if not RATE_STUDIOS:
        return
    result = graphql(FIND_STUDIO, {"id": entity_id}).get("findStudio")
    if result:
        try:
            rate_studio(result, global_mean)
        except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
            log.error(f"ERROR rating studio {result.get('name', entity_id)}: {e}")


def _handle_group_hook(entity_id, global_mean):
    if not RATE_GROUPS:
        return
    result = graphql(FIND_GROUP, {"id": entity_id}).get("findGroup")
    if result:
        try:
            rate_group(result, global_mean)
        except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
            log.error(f"ERROR rating group {result.get('name', entity_id)}: {e}")
        rate_group_ancestors(entity_id, global_mean)


def _handle_gallery_hook(entity_id, global_mean):
    if not RATE_GALLERIES:
        return
    result = graphql(FIND_GALLERY, {"id": entity_id}).get("findGallery")
    if result:
        try:
            rate_gallery(result, global_mean)
        except Exception as e:  # noqa: BLE001 - one bad entity must not abort the batch
            log.error(f"ERROR rating gallery {result.get('title') or entity_id}: {e}")


def _handle_hook(hook_ctx, global_mean):
    entity_id = hook_ctx.get("id")
    if not entity_id:
        log.error("No entity id in hook payload")
        sys.exit(1)
    hook_type = hook_ctx.get("type", "")
    if hook_type.startswith("Performer"):
        _handle_performer_hook(entity_id, global_mean)
    elif hook_type.startswith("Studio"):
        _handle_studio_hook(entity_id, global_mean)
    elif hook_type.startswith("Group"):
        _handle_group_hook(entity_id, global_mean)
    elif hook_type.startswith("Gallery"):
        _handle_gallery_hook(entity_id, global_mean)
    elif "Scene" in hook_type:
        rate_entities_from_scene(entity_id, global_mean)
    elif "Image" in hook_type:
        rate_entities_from_image(entity_id, global_mean)
    else:
        rate_entities_from_scene(entity_id, global_mean)
        rate_entities_from_image(entity_id, global_mean)


def _handle_mode(mode, global_mean):
    if mode == "rateAll":
        if RATE_PERFORMERS: rate_all_performers(global_mean)
        if RATE_STUDIOS:    rate_all_studios(global_mean)
        if RATE_GROUPS:     rate_all_groups(global_mean)
        if RATE_GALLERIES:  rate_all_galleries(global_mean)
        log.info(MSG_DONE)
        return True
    if mode == "rateAllPerformers":
        rate_all_performers(global_mean)
        log.info(MSG_DONE)
        return True
    if mode == "rateAllStudios":
        rate_all_studios(global_mean)
        log.info(MSG_DONE)
        return True
    if mode == "rateAllGroups":
        rate_all_groups(global_mean)
        log.info(MSG_DONE)
        return True
    if mode == "rateAllGalleries":
        rate_all_galleries(global_mean)
        log.info(MSG_DONE)
        return True
    return False


def main():
    global stash

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.error(f"Could not parse stdin: {raw!r}")
        sys.exit(1)

    stash = StashInterface(payload["server_connection"])

    global O_BOOST, PLAY_BOOST, WATCH_BOOST, FAVORITE_BOOST, TAG_BOOST
    global RATE_PERFORMERS, RATE_STUDIOS, RATE_GROUPS, RATE_GALLERIES

    ps = stash.get_configuration().get("plugins", {}).get("stashAutoRater", {})

    RATE_PERFORMERS = parse_bool(ps.get("rate_performers"), RATE_PERFORMERS)
    RATE_STUDIOS    = parse_bool(ps.get("rate_studios"),    RATE_STUDIOS)
    RATE_GROUPS     = parse_bool(ps.get("rate_groups"),     RATE_GROUPS)
    RATE_GALLERIES  = parse_bool(ps.get("rate_galleries"),  RATE_GALLERIES)

    O_BOOST        = parse_boost(ps.get("o_boost"),        "o_boost",        O_BOOST)
    PLAY_BOOST     = parse_boost(ps.get("play_boost"),     "play_boost",     PLAY_BOOST)
    WATCH_BOOST    = parse_boost(ps.get("watch_boost"),    "watch_boost",    WATCH_BOOST)
    FAVORITE_BOOST = parse_boost(ps.get("favorite_boost"), "favorite_boost", FAVORITE_BOOST)
    TAG_BOOST      = parse_boost(ps.get("tag_boost"),      "tag_boost",      TAG_BOOST)

    global_mean = get_global_mean()
    mode = payload.get("args", {}).get("mode")

    if _handle_mode(mode, global_mean):
        return

    _handle_hook(payload.get("args", {}).get("hookContext", {}), global_mean)


if __name__ == "__main__":
    main()
