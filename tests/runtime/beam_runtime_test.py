from tests.common.common_classes import User, Item, stateflow
from src.runtime.beam_runtime import BeamRuntime, Runtime
from apache_beam.testing.test_stream import TestStream
import apache_beam as beam
from apache_beam.testing import util as beam_test
from hamcrest import *
from hamcrest.core.base_matcher import BaseMatcher
from src.dataflow.event import Event, FunctionAddress, FunctionType, EventType
from src.dataflow.args import Arguments
import uuid
from src.serialization.json_serde import JsonSerializer


class EventMatcher(BaseMatcher):
    def __init__(
        self,
        event_id: str,
        fun_address: FunctionAddress,
        event_type: EventType,
        payload,
    ):
        self.event_id = event_id
        self.fun_address = fun_address
        self.event_type = event_type
        self.payload = payload
        self.serializer = JsonSerializer()

    def _matches(self, item) -> bool:
        key = item[0]
        event = self.serializer.deserialize_event(item[1])

        return (
            key == self.event_id
            and event.fun_address == self.fun_address
            and event.event_type == self.event_type
            and event.payload == self.payload
        )


def match_event(
    event_id: str, fun_address: FunctionAddress, event_type: EventType, payload
):
    return EventMatcher(event_id, fun_address, event_type, payload)


class TestBeamRuntime:
    INPUT = TestStream()
    OUTPUT: beam.Map = beam.Map(lambda x: x)

    def return_test_stream(self):
        return TestBeamRuntime.INPUT

    def identity(self, *args, **kwargs):
        return TestBeamRuntime.OUTPUT

    def setup_beam_runtime(self):
        self.runtime: BeamRuntime = BeamRuntime(stateflow.init(), test_mode=True)
        self.runtime._setup_kafka_client = self.return_test_stream
        self.runtime._setup_kafka_producer = self.identity

        self.runtime._setup_pipeline()

    def run_and_reset(self):
        self.runtime.run()

        # Reset environment.
        TestBeamRuntime.INPUT = TestStream()
        TestBeamRuntime.OUTPUT = beam.Map(lambda x: x)

    def test_runtime_basic(self):
        event_id: str = str(uuid.uuid4())
        event: Event = Event(
            event_id,
            FunctionAddress(FunctionType("global", "User", True), None),
            EventType.Request.InitClass,
            {"args": Arguments({"username": "wouter"})},
        )

        event_serialized = JsonSerializer().serialize_event(event)

        TestBeamRuntime.INPUT.add_elements(
            [(bytes(event_id, "utf-8"), event_serialized)]
        )
        self.setup_beam_runtime()

    def test_runtime_create_class(self):
        event_id: str = str(uuid.uuid4())
        fun_type: FunctionType = FunctionType("global", "User", True)
        event: Event = Event(
            event_id,
            FunctionAddress(fun_type, None),
            EventType.Request.InitClass,
            {"args": Arguments({"username": "wouter"})},
        )

        event_serialized = JsonSerializer().serialize_event(event)

        TestBeamRuntime.INPUT.add_elements(
            [(bytes(event_id, "utf-8"), event_serialized)]
        )

        self.setup_beam_runtime()
        beam_test.assert_that(
            self.runtime.test_output[f"{fun_type.get_full_name()}_external"],
            beam_test.matches_all(
                [
                    match_event(
                        event_id,
                        FunctionAddress(fun_type, "wouter"),
                        EventType.Reply.SuccessfulCreateClass,
                        {"key": "wouter"},
                    )
                ]
            ),
            label="CheckOutput",
        )
        self.run_and_reset()
