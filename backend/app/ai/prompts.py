"""Every prompt template in one place. Bump a *_VERSION when its prompt changes so cached results
from the old prompt aren't reused."""

COMMIT_MESSAGE_VERSION = 1

COMMIT_MESSAGE_SYSTEM = """You write commit messages for a digital painter's version history.
You get the previous version (image 1), the new version (image 2), and a measured list of the
regions that changed, with how much of each changed and how its color shifted.

Rules:
- One or two short sentences, at most 25 words, past tense, starting with a verb.
- Name the regions that changed. Trust the measured list for where and how much; use the images
  for what was actually done.
- Use painter vocabulary: palette, values, hue, saturation, rim light, silhouette, rendering,
  linework, edges, glazing, background, focal point.
- No hedging, no "the image", no "it seems", no percentages, no quotes.

Examples:
Regions: sky (62%, warmer, lighter); left figure (8%, redrawn)
Message: Warmed the sky into a dusk palette and tightened the left figure's silhouette.

Regions: hair (41%, darker, more saturated); face (12%, lighter)
Message: Deepened the hair with saturated shadows and lifted the values on the face.

Regions: whole canvas (88%, cooler, more muted)
Message: Shifted the whole palette cooler and more muted for a moonlit mood."""


def describe_regions(regions: list[dict]) -> str:
    parts = [f"{r['label']} ({round(r['changed_ratio'] * 100)}%, {', '.join(r['hints'])})" for r in regions]
    return "; ".join(parts) or "no measurable change"


def commit_message_messages(a_uri: str, b_uri: str, regions: list[dict]) -> list[dict]:
    return [
        {"role": "system", "content": COMMIT_MESSAGE_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": a_uri}},
                {"type": "image_url", "image_url": {"url": b_uri}},
                {"type": "text", "text": f"Regions: {describe_regions(regions)}\nMessage:"},
            ],
        },
    ]
