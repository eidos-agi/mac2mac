import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

ENVELOPE_TYPES = {"say", "end", "ack", "ping", "pong", "error"}


@dataclass
class Envelope:
    type: str
    content: Optional[str] = None
    reason: Optional[str] = None
    code: Optional[str] = None
    message: Optional[str] = None
    conv_id: Optional[str] = None
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    from_: str = ""
    to: str = ""
    from_agent: str = "default"
    to_agent: str = "default"
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        d = {k: v for k, v in asdict(self).items() if v is not None}
        d["from"] = d.pop("from_", "")
        return json.dumps(d)

    @classmethod
    def from_json(cls, raw: str) -> "Envelope":
        d = json.loads(raw)
        if "from" in d:
            d["from_"] = d.pop("from")
        return cls(**d)
