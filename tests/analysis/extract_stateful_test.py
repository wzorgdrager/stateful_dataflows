import pytest
from src.analysis.extract_stateful_class import ExtractStatefulFun, StatefulFun
from typing import Any, Dict
import libcst as cst


def test_nested_class_negative():
    code = """
class Test:
    class Inner:
        pass
    """
    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    with pytest.raises(AttributeError):
        code_tree.visit(visitor)


def test_class_name():
    code = """
class FancyClass:
    pass
    """
    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    code_tree.visit(visitor)

    statefun: StatefulFun = ExtractStatefulFun.create_stateful_fun(visitor)
    assert statefun.class_name == "FancyClass"


def test_merge_self_attributes_positive():
    code = """
class FancyClass:
    def __init__(self):
        self.x : int = 4
        self.x = self.no
        self.y: str
        self.z = self.z = 2
        """
    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    code_tree.visit(visitor)

    merged_attributes: Dict[str, Any] = visitor.merge_self_attributes()
    final_dict = {"x": "int", "y": "str", "z": "NoType"}

    assert merged_attributes == final_dict


def test_merge_self_attributes_multiple_fun_positive():
    code = """
class FancyClass:
    def __init__(self):
        self.x = 4
        self.x = self.no
        self.i = r = 3
        self.q, no = 2
    
    def other_fun(self):
        self.x: int
        self.y: List[str]
        self.z = 3
        self.p += 3
        """
    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    code_tree.visit(visitor)

    merged_attributes: Dict[str, Any] = visitor.merge_self_attributes()
    final_dict = {
        "x": "int",
        "y": "List[str]",
        "z": "NoType",
        "p": "NoType",
        "i": "NoType",
        "q": "NoType",
    }

    assert merged_attributes == final_dict


def test_merge_self_attributes_conflict():
    code = """
class FancyClass:
    def __init__(self):
        self.x : int = 4
        self.x : str
        """
    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    code_tree.visit(visitor)

    with pytest.raises(AttributeError):
        visitor.merge_self_attributes()


def test_async_func_error():
    code = """
class FancyClass:
    def __init__(self):
        self.x : int = 4
        self.x : str
        
    async def fun(self):
        pass
            """
    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    with pytest.raises(AttributeError):
        code_tree.visit(visitor)


def test_param_extraction_not_allow_default_values():
    code = """
class FancyClass:
    def __init__(self):
        self.x : int = 4

    def fun(self, x: int = 3):
        pass
"""
    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    with pytest.raises(AttributeError):
        code_tree.visit(visitor)


def test_param_extraction_positive():
    code = """
class FancyClass:
    def __init__(self):
        self.x : int = 4

    def fun(self, x: int, y: str, z):
        pass
    """

    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)
    code_tree.visit(visitor)

    method = visitor.method_descriptor[1]
    fun_params = {"x": "int", "y": "str", "z": "NoType"}
    assert method.input_desc == fun_params


def test_param_extraction_no_args():
    code = """
class FancyClass:
    def __init__(self):
        self.x : int = 4

    def fun(self, *not_allowed):
        pass
    """

    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    with pytest.raises(AttributeError):
        code_tree.visit(visitor)


def test_param_extraction_no_kwargs():
    code = """
class FancyClass:
    def __init__(self):
        self.x : int = 4

    def fun(self, **not_allowed):
        pass
    """

    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    with pytest.raises(AttributeError):
        code_tree.visit(visitor)


def test_param_extraction_no_arguments():
    code = """
class FancyClass:
    def __init__(self):
        self.x : int = 4

    def fun(self):
        pass
    """

    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    code_tree.visit(visitor)

    method = visitor.method_descriptor[1]
    fun_params = {}
    assert method.input_desc == fun_params


def test_method_extraction_read_only():
    code = """
class FancyClass:
    def __init__(self):
        self.x : int = 4

    def fun(self):
        x = 3
        y = self.x
        
    def fun_other(self):
        self.y = 2
    """

    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    code_tree.visit(visitor)

    method = visitor.method_descriptor[1]
    assert method.read_only == True

    method = visitor.method_descriptor[2]
    assert method.read_only == False


def test_method_extraction_attribute_error_call():
    code = """
class FancyClass:
    def __init__(self):
        self.x : int = 4

    def fun(self):
        x = 3
        y = self.x

    def fun_other(self, item):
        item.buy(self.x)
    """

    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    with pytest.raises(AttributeError):
        code_tree.visit(visitor)


def test_method_extraction_attribute_error_access():
    code = """
class FancyClass:
    def __init__(self):
        self.x : int = 4

    def fun(self):
        x = 3
        y = self.x

    def fun_other(self, item):
        item.buy = 4
    """

    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)

    with pytest.raises(AttributeError):
        code_tree.visit(visitor)


def test_method_extraction_attribute_no_error():
    code = """
class FancyClass:
    def __init__(self):
        self.x : int = 4

    def fun(self):
        x = 3
        y = self.x

    def fun_other(self, item: Item):
        item.buy = 4
        item.call(self.x)
    """

    code_tree = cst.parse_module(code)
    visitor = ExtractStatefulFun(code_tree)
    code_tree.visit(visitor)
