import importlib.util
from pathlib import Path


def load_validator():
    path = Path(__file__).resolve().parents[1] / 'scripts/validate_itc_saved.py'
    spec = importlib.util.spec_from_file_location('itc_validator', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate


def test_validator_feasibility_and_soft_objective(tmp_path):
    instance = tmp_path / 'example.ctt'
    instance.write_text('''Name: test
Courses: 1
Rooms: 1
Days: 2
Periods_per_day: 2
Curricula: 1
Constraints: 0
COURSES:
c teacher 2 2 20
ROOMS:
r 10
CURRICULA:
cur 1 c
UNAVAILABILITY_CONSTRAINTS:
END.
''')
    solution = tmp_path / 'example.sol'
    solution.write_text('c r 0 0\nc r 1 0\n')
    validate = load_validator()
    result = validate(instance, solution)
    assert result['feasibility'] == 'valid'
    assert result['objective_value'] == 24  # capacity 20 + isolated curriculum lectures 4
    solution.write_text('c r 0 0\nc r 0 0\n')
    result = validate(instance, solution)
    assert result['feasibility'] == 'invalid'
    assert result['objective_value'] is None


def test_missing_lectures_cannot_receive_low_cost(tmp_path):
    instance = tmp_path / 'example.ctt'
    instance.write_text('''Name: test
Courses: 1
Rooms: 1
Days: 1
Periods_per_day: 2
Curricula: 0
Constraints: 0
COURSES:
c teacher 2 1 5
ROOMS:
r 10
CURRICULA:
UNAVAILABILITY_CONSTRAINTS:
END.
''')
    solution = tmp_path / 'example.sol'
    solution.write_text('c r 0 0\n')
    assert load_validator()(instance, solution)['objective_value'] is None
