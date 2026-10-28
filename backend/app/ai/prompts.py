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


BLEND_SEAM_VERSION = 1

BLEND_SEAM = (
    "This is a crop of a digital painting where one area was brought back from an earlier version. "
    "Blend the seam where the two painted areas meet so the transition looks painted, not pasted: "
    "match brushwork, edges and lighting across it. Do not change anything else."
)


NOTE_SUMMARY_VERSION = 1

NOTE_SUMMARY = {
    "artist": (
        "Summarize this note an artist recorded about a version of their painting in one sentence, "
        "first person, keeping the reason for the change. No preamble."
    ),
    "client": (
        "This is feedback a client gave on a version of a painting. List the changes they are asking for "
        "as short imperative bullet points (\"- Make the sky dusk\"), at most 5. No preamble."
    ),
}

CAPTION_VERSION = 1

CAPTION = (
    "Describe this artwork in one or two sentences for a search index: subject, the main elements "
    "(sky, figures, hair, clothing, background), palette, lighting and mood. Plain words, no preamble."
)

QUERY_REWRITE_VERSION = 1

QUERY_REWRITE = """Turn a search over an artist's version history into JSON.
Fields:
- "relation": "before", "after" or "when" if the query is about a moment in the history, else null
- "anchor": words describing the change that marks that moment (for "before I changed the sky": "sky")
- "terms": other words to search for, or ""
Reply with the JSON object only.

Query: show me the version before I changed the sky
{"relation": "before", "anchor": "sky", "terms": ""}

Query: dusk palette
{"relation": null, "anchor": "", "terms": "dusk palette"}

Query: what did the hair look like after the client feedback
{"relation": "after", "anchor": "client feedback", "terms": "hair"}"""

EXPLORE_VERSION = 1

EXPLORE_DIRECTIONS = """An artist asked to explore variations of their painting: "{prompt}".
Give exactly three distinct palette or lighting directions, 2 to 5 words each, as a JSON list of strings.
Example: ["warm golden hour", "cool moonlit night", "muted overcast"]. Reply with the JSON list only."""

EXPLORE_EDIT = (
    "Recolor this artwork to a {direction} palette and lighting. Keep the composition, linework, "
    "shapes and every detail exactly the same; change only color and light."
)


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
