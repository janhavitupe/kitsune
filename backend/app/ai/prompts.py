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


ASSISTANT_SYSTEM = """You are the studio assistant in Kitsune, version control for a digital painter.
You work on their version history with tools. Versions are called v1, v2, ... in order.

Rules:
- Never overwrite anything. Every image you make becomes a new version on a separate assistant branch.
- You start from the "working version" given below. bring_back and adjust change the working version
  (each makes a new one); try_variant makes a side branch and leaves the working version alone.
- Region names come from get_changes: they describe what changed between two versions
  ("sky", or "top area" when regions aren't named yet). Use those exact names with bring_back.
- Use at most 6 tool calls. When done, reply with one or two plain sentences saying what you made.
"""

ASSISTANT_PLAN = (
    "Before using any tool, reply with a short numbered plan (2 to 5 steps, one line each) for this ask. "
    "Plan only: no tool calls yet."
)

ASSISTANT_GO = "Now carry out the plan with the tools. Stop when it's done and summarize in one or two sentences."

STORY_VERSION = 1

STORY = """Write a portfolio process breakdown for this digital painting, from the artist's point of view
(first person), in markdown: a short title line starting with "# ", then 4 to 7 short sections, each
starting with "## ". Refer to versions as [v3] so they can be shown as thumbnails. Use the notes for
the reasons behind changes and credit client feedback where it shaped the piece. No invented details
beyond what the history says. History:

{history}"""


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
