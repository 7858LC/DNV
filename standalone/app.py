"""
Meeting Minutes – standalone app.
Run: python app.py
Then open the URL printed in the console on any device on the same Wi-Fi.
"""
from __future__ import annotations
import json
import os
import socket
import ssl
import datetime
import ipaddress
from pathlib import Path
from datetime import date
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

CANDIDATE_PORTS = [5200, 5201, 5202]

SYSTEM_PROMPT = """You are a technical meeting minutes formatter. Convert raw transcripts or rough notes into concise, structured meeting minutes that match the user's voice exactly.

STYLE RULES:
- Bullets are short and direct — no narrative, no filler, no passive voice
- Preserve technical jargon, document numbers, and proper nouns exactly as spoken
- Use names directly when attributing a statement or decision (e.g. "Chris - we will manufacture to C101")
- Action items are written as imperatives ("Add...", "Look for...", "Review...")
- Nested bullets only for genuinely subordinate sub-points
- No "The team discussed..." or "It was noted that..." — just the fact
- If a physical measurement appears in metric, append the imperial equivalent in parentheses — e.g. "50 mm (2 in)", "10 kN (2,250 lbf)", "200 MPa (29 ksi)". If already imperial, leave it. Do NOT convert document numbers, part numbers, bolt grades, or standard codes (e.g. C101, M16, S355 are not measurements)

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


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def find_free_port() -> int:
    for port in CANDIDATE_PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


def make_ssl_files(lan_ip: str) -> tuple[str, str] | None:
    """Generate a self-signed cert using the cryptography package."""
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "minutes")])
        san_list = [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]
        try:
            san_list.append(x509.IPAddress(ipaddress.IPv4Address(lan_ip)))
        except Exception:
            pass

        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
            .sign(key, hashes.SHA256())
        )

        base = Path(__file__).parent
        cert_path = base / "cert.pem"
        key_path  = base / "key.pem"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
        return str(cert_path), str(key_path)
    except Exception as e:
        import traceback
        print(f"  [!] Could not create HTTPS cert: {e}")
        traceback.print_exc()
        return None


@app.route("/")
def index():
    today = date.today().strftime("%-m/%-d/%y") if os.name != "nt" else date.today().strftime("%#m/%#d/%y")
    return render_template("index.html", today=today)


@app.route("/api/process", methods=["POST"])
def process():
    try:
        import anthropic
    except ImportError:
        return jsonify({"error": "Run: pip install anthropic"}), 500

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500

    body = request.get_json(force=True)
    transcript = (body.get("transcript") or "").strip()
    if not transcript:
        return jsonify({"error": "No transcript provided"}), 400

    parts = []
    if body.get("title"):
        parts.append(f"Meeting: {body['title']}")
    if body.get("date"):
        time_str = ""
        if body.get("time_from") or body.get("time_to"):
            time_str = "  " + " – ".join(filter(None, [body.get("time_from",""), body.get("time_to","")]))
        parts.append(f"Date: {body['date']}{time_str}")
    groups = [g.strip() for g in body.get("attendee_groups", []) if g.strip()]
    if groups:
        parts.append("Attendees:\n" + "\n".join(f"  Group {i+1}: {g}" for i, g in enumerate(groups)))
    parts.append(f"\nTranscript:\n{transcript}")

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n".join(parts)}],
    )

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]

    return jsonify(json.loads(raw))


@app.route("/api/export", methods=["POST"])
def export():
    body = request.get_json(force=True)
    meeting_date = body.get("date", "")
    time_from    = body.get("time_from", "")
    time_to      = body.get("time_to", "")
    title        = body.get("title", "")
    groups       = [g.strip() for g in body.get("attendee_groups", []) if g.strip()]
    minutes_text = body.get("minutes", "")
    action_items = body.get("action_items", [])

    lines = []
    if meeting_date:
        time_str = ("  " + " – ".join(filter(None, [time_from, time_to]))) if (time_from or time_to) else ""
        lines.append(meeting_date + time_str)
    for g in groups:
        lines.append(f"• {g}")
    if title:
        lines.append(f"• {title}")
    if lines:
        lines.append("")
    for line in minutes_text.split("\n"):
        lines.append(line.replace("•", "-").replace("\t", "  "))
    if action_items:
        lines += ["", "## Action Items", "", "| Task | Owner | Due |", "|------|-------|-----|"]
        for item in action_items:
            lines.append(f"| {item.get('task','')} | {item.get('owner','TBD')} | {item.get('due','')} |")

    md = "\n".join(lines)
    safe_title = title.replace(" ", "_").replace("/", "-") or "meeting"
    safe_date  = meeting_date.replace("/", "-") or "date"
    filename   = f"minutes_{safe_date}_{safe_title}.md"

    return Response(md, mimetype="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


if __name__ == "__main__":
    # Keep Windows awake while app is running (no admin needed)
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED

    port   = find_free_port()
    lan_ip = get_lan_ip()
    ssl_files = make_ssl_files(lan_ip)
    proto = "https" if ssl_files else "http"

    print()
    print("  ┌─────────────────────────────────────────────┐")
    print("  │          MEETING MINUTES — RUNNING          │")
    print("  ├─────────────────────────────────────────────┤")
    print(f"  │  LOCAL   {proto}://localhost:{port:<18}│")
    print(f"  │  PHONE   {proto}://{lan_ip}:{port:<15}│")
    if ssl_files:
        print("  │                                             │")
        print("  │  Phone: tap Advanced → Proceed on the       │")
        print("  │  cert warning (self-signed, normal).        │")
    print("  │                                             │")
    print("  │  Press Ctrl+C to stop.                      │")
    print("  └─────────────────────────────────────────────┘")
    print()

    app.run(host="0.0.0.0", port=port, debug=False,
            ssl_context=ssl_files if ssl_files else None)
