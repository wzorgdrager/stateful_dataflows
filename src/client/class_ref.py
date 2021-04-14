from src.descriptors import ClassDescriptor, MethodDescriptor
from src.client.future import StateflowFuture
from src.dataflow.args import Arguments
from typing import List
from src.dataflow.event import Event, EventType, EventFlowNode
from src.client.stateflow_client import StateflowClient
import uuid
from src.serialization.json_serde import JsonSerializer


class MethodRef:
    def __init__(
        self, method_name: str, class_ref: "ClassRef", method_desc: MethodDescriptor
    ):
        self.method_name = method_name
        self._class_ref = class_ref
        self.method_desc = method_desc

    def __call__(self, *args, **kwargs) -> StateflowFuture:
        # print(
        #     f"Now invoking method: {self.method_name}, with arguments: {args} and {kwargs}."
        # )

        if self.method_desc.is_splitted_function():
            print(f"Now calling a splitted function! {self.method_name}")
            return self._class_ref.invoke_flow(
                self.method_desc.flow_list,
                Arguments.from_args_and_kwargs(
                    self.method_desc.input_desc.get(), *args, **kwargs
                ),
            )

        return self._class_ref.invoke_method(
            self.method_name,
            Arguments.from_args_and_kwargs(
                self.method_desc.input_desc.get(), *args, **kwargs
            ),
        )


class ClassRef(object):
    from src.dataflow.event import FunctionAddress

    __slots__ = "_fun_addr", "_class_desc", "_attributes", "_methods", "_client"

    def __init__(
        self,
        fun_addr: FunctionAddress,
        class_desc: ClassDescriptor,
        client: StateflowClient,
    ):
        self._fun_addr = fun_addr
        self._class_desc = class_desc
        self._attributes = list(class_desc.state_desc.get_keys())
        self._methods = {
            method.method_name: method for method in class_desc.methods_dec
        }
        self._client = client

    def invoke_method(self, method_name: str, args: Arguments) -> StateflowFuture:
        payload = {"args": args, "method_name": method_name}
        event_id: str = str(uuid.uuid4())

        invoke_method_event = Event(
            event_id, self._fun_addr, EventType.Request.InvokeStateful, payload
        )

        return self._client.send(invoke_method_event)

    def invoke_flow(self, flow: List[EventFlowNode], args: Arguments):
        flow_dict = {}

        to_assign = list(args.get_keys())

        for f in flow:
            for arg in to_assign:
                if arg in f.input and not isinstance(args[arg], ClassRef):
                    f.input[arg] = args[arg]
                    to_assign.remove(arg)
                elif (
                    isinstance(args[arg], ClassRef)
                    and f.typ == EventFlowNode.REQUEST_STATE
                ):
                    f.input["key"] = args[arg]._fun_addr.key
                    to_assign.remove(arg)

            flow_dict[f.id] = {"node": f.to_dict(), "status": "PENDING"}

        flow_dict[0]["status"] = "FINISHED"

        payload = {"flow": flow_dict, "current_flow": 1}
        event_id: str = str(uuid.uuid4())

        invoke_flow_event = Event(
            event_id, self._fun_addr, EventType.Request.EventFlow, payload
        )

        print(JsonSerializer().serialize_event(invoke_flow_event))

        # return self._client.send(invoke_flow_event)

    def get_attribute(self, attr: str) -> StateflowFuture:
        payload = {"attribute": attr}
        event_id: str = str(uuid.uuid4())

        invoke_method_event = Event(
            event_id, self._fun_addr, EventType.Request.GetState, payload
        )

        return self._client.send(invoke_method_event)

    def set_attribute(self, attr: str, new) -> StateflowFuture:
        payload = {"attribute": attr, "attribute_value": new}
        event_id: str = str(uuid.uuid4())

        invoke_method_event = Event(
            event_id, self._fun_addr, EventType.Request.UpdateState, payload
        )
        return self._client.send(invoke_method_event)

    def __getattr__(self, item):
        if item in self._attributes:
            # print(f"Attribute access: {item}")
            return self.get_attribute(item)

        if item in self._methods.keys():
            # print(f"Method invocation: {item}")
            return MethodRef(item, self, self._methods[item])

        return object.__getattribute__(self, item)

    def __setattr__(self, key, value):
        if key not in self.__slots__:
            # print(f"Attribute update: {key}")
            return self.set_attribute(key, value)

        return object.__setattr__(self, key, value)

    def __str__(self):
        return f"Class reference for {self._fun_addr.function_type.name} with key {self._fun_addr.key}."
