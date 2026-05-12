from __future__ import annotations

import json
import os
from datetime import date
from flask import Blueprint, render_template, request, jsonify, Response

meeting_minutes_bp = Blueprint("meeting_minutes", __name__)

SYSTEM_PROMPT = """You are a technical meeting minutes formatter. Convert raw transcripts or rough notes into concise, structured meeting minutes that match the user's voice exactly.

STYLE RULES:
- Bullets are short and direct — no narrative, no filler, no passive voice
- Preserve technical jargon, document numbers, and proper nouns exactly as spoken
- Use names directly when attributing a statement or decision (e.g. "Chris - we will manufacture to C101")
- Action items are written as imperatives ("Add...", "Look for...", "Review...")
- Nested bullets only for genuinely subordinate sub-points
- No "The team discussed..." or "It was noted that..." — just the fact

EXAMPLE INPUT (rough transcript):
"We kicked off the structural PDR today. Mathias is going to help because he has experience with large oddly shaped deployments and with concrete. Sebastian will be the main structural expert. Larry's tracker should be done by end of this week. We need to look at the leak path through the viewport retention bolts. We should add the viewport preliminary analysis to the package. Oli and Alfie might have comments on the AIP, or we can find them on Veracity. Chris confirmed we're manufacturing to C101, not SHIPS. He also asked about the hull finish - it will be sealed but that's not defined yet, same for the stiffener edges. For the analysis there are two steps - first just steel no concrete, then add concrete to check interface stresses. Oli brought up starting an ITP. We also need to add a stripped down ANSYS model."

EXAMPLE OUTPUT:
{
  "minutes": "• Structural PDR Kickoff\\n• Mathias will support: experience with large, oddly-shaped deployments and with concrete\\n• Sebastian will be main structural expert\\n• Tracker that Larry built should be functional by the end of this week\\n• Leak path through viewport retention bolts\\n• Add viewport preliminary analysis to package\\n• Look for comments on AIP on Veracity or get from Oli/Alfie\\n• Chris - we will manufacture to C101, not SHIPS\\n• Chris asked about finish of hull - will be sealed, but not yet defined (stiffener edges too)\\n• Two steps for analysis\\n\\t• One with just steel, no concrete\\n\\t• Another with concrete to check interface stresses, etc.\\n• Oli thinks we should start an ITP\\n• Add stripped down ANSYS model",
  "action_items": [
    {"task": "Add viewport preliminary analysis to package", "owner": "TBD", "due": ""},
    {"task": "Look for comments on AIP on Veracity", "owner": "TBD", "due": ""},
    {"task": "Tracker functional", "owner": "Larry", "due": "End of this week"},
    {"task": "Start ITP", "owner": "Oli", "due": ""},
    {"task": "Add stripped down ANSYS model", "owner": "TBD", "due": ""}
  ]
}

Return ONLY valid JSON matching the structure above. No markdown fences, no explanation."""


def _call_claude(transcript: str, metadata: dict) -> dict:
    try:
        import anthropic
    except ImportError:
        return {"error": "anthropic package not installed. Run: pip install anthropic"}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY environment variable not set"}

    client = anthropic.Anthropic(api_key=api_key)

    parts = []
    if metadata.get("title"):
        parts.append(f"Meeting: {metadata['title']}")
    if metadata.get("date"):
        parts.append(f"Date: {metadata['date']}")
    attendee_groups = [g.strip() for g in metadata.get("attendee_groups", []) if g.strip()]
    if attendee_groups:
        parts.append("Attendees:\n" + "\n".join(f"  Group {i+1}: {g}" for i, g in enumerate(attendee_groups)))
    parts.append(f"\nTranscript:\n{transcript}")

    user_message = "\n".join(parts)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()
    # Strip markdown fences if model added them anyway
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]

    return json.loads(raw)


@meeting_minutes_bp.route("/meeting-minutes")
def meeting_minutes_page():
    today = date.today().strftime("%-m/%-d/%y")
    return render_template("meeting_minutes.html", today=today)


@meeting_minutes_bp.route("/api/meeting-minutes/process", methods=["POST"])
def process_minutes():
    body = request.get_json(force=True)
    transcript = (body.get("transcript") or "").strip()
    if not transcript:
        return jsonify({"error": "No transcript provided"}), 400

    metadata = {
        "title": body.get("title", ""),
        "date": body.get("date", ""),
        "attendee_groups": body.get("attendee_groups", []),
    }

    result = _call_claude(transcript, metadata)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@meeting_minutes_bp.route("/api/meeting-minutes/export", methods=["POST"])
def export_minutes():
    body = request.get_json(force=True)
    meeting_date = body.get("date", "")
    title = body.get("title", "")
    attendee_groups = [g.strip() for g in body.get("attendee_groups", []) if g.strip()]
    minutes_text = body.get("minutes", "")
    action_items = body.get("action_items", [])

    lines = []
    if meeting_date:
        lines.append(meeting_date)
    if attendee_groups:
        for g in attendee_groups:
            lines.append(f"• {g}")
    if title:
        lines.append(f"• {title}")
    if lines:
        lines.append("")

    # Convert bullet char to markdown list
    for line in minutes_text.split("\n"):
        lines.append(line.replace("•", "-").replace("\t", "  "))

    if action_items:
        lines.append("")
        lines.append("## Action Items")
        lines.append("")
        lines.append("| Task | Owner | Due |")
        lines.append("|------|-------|-----|")
        for item in action_items:
            task = item.get("task", "")
            owner = item.get("owner", "TBD")
            due = item.get("due", "")
            lines.append(f"| {task} | {owner} | {due} |")

    md_content = "\n".join(lines)

    safe_title = title.replace(" ", "_").replace("/", "-") if title else "meeting"
    safe_date = meeting_date.replace("/", "-") if meeting_date else "date"
    filename = f"minutes_{safe_date}_{safe_title}.md"

    return Response(
        md_content,
        mimetype="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
