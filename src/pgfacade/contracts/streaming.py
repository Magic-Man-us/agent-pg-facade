from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from pgfacade.contracts.enums import StreamOperation
from pgfacade.contracts.envelopes import Failure, Success
from pgfacade.contracts.events import Notification
from pgfacade.contracts.types import NotificationChannels
from pgfacade.shared.config import CONTRACT_CONFIG
from pgfacade.shared.types import HeartbeatSeconds


class EventStreamInput(BaseModel):
    model_config = CONTRACT_CONFIG

    channels: NotificationChannels
    heartbeat_s: HeartbeatSeconds = 15.0


class EventStreamRequest(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal[StreamOperation.EVENT_STREAM] = StreamOperation.EVENT_STREAM
    input: EventStreamInput


class EventStreamResponse(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal[StreamOperation.EVENT_STREAM] = StreamOperation.EVENT_STREAM
    outcome: Annotated[Success[Notification] | Failure, Field(discriminator="status")]
