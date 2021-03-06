import uuid
from tests.context import stateflow
import pytest

from tests.common.common_classes import stateflow
from stateflow.dataflow.event import Event, EventType
from stateflow.dataflow.address import FunctionAddress, FunctionType
from stateflow.dataflow.args import Arguments
from stateflow.dataflow.state import State
from stateflow.dataflow.stateful_operator import StatefulOperator
from stateflow.serialization.json_serde import JsonSerializer


@pytest.fixture(scope="session", autouse=True)
def setup():
    flow = stateflow.init()
    item_operator = flow.operators[0]
    item_operator.serializer = JsonSerializer()
    user_operator = flow.operators[1]
    user_operator.serializer = JsonSerializer()
    yield user_operator, item_operator


class TestStatefulOperator:
    def test_init_class_positive(self, setup):
        operator: StatefulOperator = setup[0]

        event_id = str(uuid.uuid4())
        event = Event(
            event_id,
            FunctionAddress(FunctionType("global", "User", True), None),
            EventType.Request.InitClass,
            {"args": Arguments({"username": "wouter"})},
        )

        return_event = operator.handle_create(event)

        assert return_event.event_id == event_id
        assert return_event.fun_address.key == "wouter"
        assert return_event.payload == {
            "init_class_state": {"username": "wouter", "balance": 0, "items": []}
        }

    def test_handle_init_class_positive(self, setup):
        operator: StatefulOperator = setup[0]

        event_id = str(uuid.uuid4())
        event = Event(
            event_id,
            FunctionAddress(FunctionType("global", "User", True), None),
            EventType.Request.InitClass,
            {"args": Arguments({"username": "wouter"})},
        )

        intermediate_event = operator.handle_create(event)
        return_event, state = operator.handle(intermediate_event, None)

        assert state is not None
        assert return_event.event_type == EventType.Reply.SuccessfulCreateClass
        assert return_event.payload["key"] == "wouter"

    def test_handle_init_class_negative(self, setup):
        operator: StatefulOperator = setup[0]

        event_id = str(uuid.uuid4())
        event = Event(
            event_id,
            FunctionAddress(FunctionType("global", "User", True), None),
            EventType.Request.InitClass,
            {"args": Arguments({"username": "wouter"})},
        )

        intermediate_event = operator.handle_create(event)
        return_event, state = operator.handle(intermediate_event, "non_empty_state")

        assert state == "non_empty_state"
        assert return_event.event_type == EventType.Reply.FailedInvocation
        assert return_event.payload["error_message"]

    def test_invoke_stateful_positive(self, setup):
        operator: StatefulOperator = setup[0]

        event_id = str(uuid.uuid4())
        event = Event(
            event_id,
            FunctionAddress(FunctionType("global", "User", True), "wouter"),
            EventType.Request.InvokeStateful,
            {"args": Arguments({"x": 5}), "method_name": "update_balance"},
        )

        state = State({"username": "wouter", "balance": 10, "items": []})
        return_event, updated_state_bytes = operator.handle(
            event, TestStatefulOperator.state_to_bytes(state)
        )
        updated_state = TestStatefulOperator.bytes_to_state(updated_state_bytes)

        assert return_event.event_type == EventType.Reply.SuccessfulInvocation
        assert return_event.payload["return_results"] is None
        assert updated_state["balance"] == 15

    def test_invoke_stateful_negative(self, setup):
        operator: StatefulOperator = setup[0]

        event_id = str(uuid.uuid4())
        event = Event(
            event_id,
            FunctionAddress(FunctionType("global", "User", True), "wouter"),
            EventType.Request.InvokeStateful,
            {"args": Arguments({"x": "100"}), "method_name": "update_balance"},
        )

        state = State({"username": "wouter", "balance": 10, "items": []})
        return_event, updated_state_bytes = operator.handle(
            event, TestStatefulOperator.state_to_bytes(state)
        )
        updated_state = TestStatefulOperator.bytes_to_state(updated_state_bytes)

        assert return_event.event_type == EventType.Reply.FailedInvocation
        assert updated_state["balance"] == 10

    def test_get_state_positive(self, setup):
        operator: StatefulOperator = setup[0]

        event_id = str(uuid.uuid4())
        event = Event(
            event_id,
            FunctionAddress(FunctionType("global", "User", True), "wouter"),
            EventType.Request.GetState,
            {"attribute": "balance"},
        )

        state = State({"username": "wouter", "balance": 11, "items": []})
        return_event, updated_state_bytes = operator.handle(
            event, TestStatefulOperator.state_to_bytes(state)
        )
        updated_state = TestStatefulOperator.bytes_to_state(updated_state_bytes)

        assert return_event.event_type == EventType.Reply.SuccessfulStateRequest
        assert return_event.payload["state"] == 11
        assert state.get() == updated_state.get()  # State is not updated.

    def test_update_state_positive(self, setup):
        operator: StatefulOperator = setup[0]

        event_id = str(uuid.uuid4())
        event = Event(
            event_id,
            FunctionAddress(FunctionType("global", "User", True), "wouter"),
            EventType.Request.UpdateState,
            {"attribute": "balance", "attribute_value": 8},
        )

        state = State({"username": "wouter", "balance": 11, "items": []})
        return_event, updated_state_bytes = operator.handle(
            event, TestStatefulOperator.state_to_bytes(state)
        )
        updated_state = TestStatefulOperator.bytes_to_state(updated_state_bytes)

        assert return_event.event_type == EventType.Reply.SuccessfulStateRequest
        assert return_event.payload == {}
        assert updated_state.get()["balance"] == 8
        assert state.get() != updated_state.get()  # State is updated.

    def test_find_class_positive(self, setup):
        operator: StatefulOperator = setup[0]

        event_id = str(uuid.uuid4())
        event = Event(
            event_id,
            FunctionAddress(FunctionType("global", "User", True), "wouter"),
            EventType.Request.FindClass,
            {},
        )

        state = State({"username": "wouter", "balance": 11, "items": []})
        return_event, updated_state_bytes = operator.handle(
            event, TestStatefulOperator.state_to_bytes(state)
        )
        updated_state = TestStatefulOperator.bytes_to_state(updated_state_bytes)

        assert return_event.event_type == EventType.Reply.FoundClass
        assert return_event.payload == {}
        assert state.get() == updated_state.get()  # State is updated.

    def test_state_does_not_exist_no_init_class(self, setup):
        operator: StatefulOperator = setup[0]

        event_id = str(uuid.uuid4())
        event = Event(
            event_id,
            FunctionAddress(FunctionType("global", "User", True), "wouter"),
            EventType.Request.InvokeStateful,
            {"args": Arguments({"x": "100"}), "method_name": "update_balance"},
        )

        return_event, updated_state = operator.handle(event, None)

        assert return_event.event_type == EventType.Reply.KeyNotFound
        assert updated_state is None

    @staticmethod
    def bytes_to_state(state: bytes) -> State:
        return State(JsonSerializer().deserialize_dict(state))

    @staticmethod
    def state_to_bytes(state: State) -> bytes:
        return bytes(JsonSerializer().serialize_dict(state.get()), "utf-8")
