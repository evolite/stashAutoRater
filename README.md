# Stash Auto Rater

Automatically rates performers, studios, groups, and galleries in Stash based on how you've rated their scenes and images. Each entity type can be enabled or disabled independently in plugin settings.

## How it works

Ratings use a Bayesian average: new entities start near your library's mean and converge toward their true average as you rate more of their content. This prevents a single 5-star scene from inflating an entity you've barely seen.

Optional boosts add points on top of that average. Each boost has a multiplier you set (default 0 = off). Most use a log scale — the bonus grows with engagement but tapers off, so the difference between 1 and 10 plays matters more than between 100 and 110. The favourite boost is a flat addition. The tag boost accumulates once per favourited tag across all scenes and images, so entities whose content matches several of your favourite tags benefit more than those who only match one.

Configure everything under Settings → Plugins → Stash Auto Rater. Start boost multipliers small (1–2) and adjust to taste.

## Usage

**Automatic** — runs whenever you update a scene, image, performer, studio, group, or gallery. A scene update also re-rates all performers, the studio, and any groups it belongs to; an image update does the same for galleries.

**Manual** — Settings → Plugins → Stash Auto Rater → Rate All (or per-type tasks). Use these after o-count changes, which don't trigger the hook.

## Requirements

- Python 3
- [stashapi](https://github.com/stashapp/stash-app-python-client) (included in the official Stash Docker image)
