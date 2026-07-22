import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_marketlab_research_cycle.py"
SPEC = importlib.util.spec_from_file_location("marketlab_research_cycle", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CORE_STEPS = MODULE.CORE_STEPS
SHADOW_STEPS = MODULE.SHADOW_STEPS
OPTIMIZATION_STEPS = MODULE.OPTIMIZATION_STEPS
build_steps = MODULE.build_steps


def test_optimization_mode_does_not_repeat_core_research_steps() -> None:
    assert build_steps("optimization") == OPTIMIZATION_STEPS
    assert not {name for name, _command in CORE_STEPS} & {
        name for name, _command in build_steps("optimization")
    }


def test_light_and_full_modes_keep_expected_step_order() -> None:
    assert build_steps("light")[: len(CORE_STEPS)] == CORE_STEPS
    assert build_steps("full")[: len(CORE_STEPS)] == CORE_STEPS
    assert build_steps("full")[len(CORE_STEPS) : len(CORE_STEPS) + len(SHADOW_STEPS)] == SHADOW_STEPS
    start = len(CORE_STEPS) + len(SHADOW_STEPS)
    assert build_steps("full")[start : start + len(OPTIMIZATION_STEPS)] == OPTIMIZATION_STEPS


def test_shadow_mode_runs_only_shadow_research() -> None:
    assert build_steps("shadow") == SHADOW_STEPS
    assert not {name for name, _command in CORE_STEPS} & {
        name for name, _command in build_steps("shadow")
    }
