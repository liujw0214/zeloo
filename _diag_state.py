import importlib.util
import sys

_root = importlib.util.spec_from_file_location("_zeloo_state_root", "zeloo_state.py")
_root_mod = importlib.util.module_from_spec(_root)
sys.modules["_zeloo_state_root"] = _root_mod
_root.loader.exec_module(_root_mod)
print("Root module:", _root_mod)
print("SessionDB from root:", _root_mod.SessionDB)
print("Has create_session:", hasattr(_root_mod.SessionDB, "create_session"))
