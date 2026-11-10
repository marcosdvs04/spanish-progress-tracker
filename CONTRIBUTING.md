# Contributing

Thanks for looking. This project has a few rules that are not style preferences —
they are the controls the design depends on, and a change that breaks one of them
is a change to the product, not a refactor.

## Non-negotiable

1. **No real learner data.** Not in fixtures, not in tests, not in a commit message,
   not pasted into an AI tool. `tests/test_p1_privacy.py` fails the build on anything
   that looks like it.
2. **Only `gateway/` may reach the network.** `tests/test_architecture.py` enforces this.
   If you need data from somewhere, it goes through the gateway or it does not happen.
3. **Nothing may gain the ability to transmit to a person.** No email client, no webhook,
   no messaging SDK. The output of this system is a file.
4. **Only the export service writes to the validated store**, and only after approval.
5. **P1 test assertions are written by hand.** A test written by the same tool that wrote
   the code under test is not independent evidence, and P1 is where independence matters.

## Workflow

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # must be green before you push
python -m progress_tracker.cli demo      # must run end to end
```

Commits: imperative mood, one concern each, and say *why* in the body when the change
touches a gate, a state transition or a control.

## Adding a model provider

Write one class in `gateway/` with `model_id` and `invoke(ModelRequest) -> ModelResponse`,
add a branch to `build_adapter`, and change nothing else. If you find yourself editing a
service to accommodate a provider, the abstraction has leaked and the fix belongs in the
gateway.

## Adding an error category

Categories live in the tutor-editable settings store (D6), not in code. Add a key and a
human label, plus trigger phrases in `gateway/stub.py` if you want the offline stub to
recognise it. A category the model returns that is not in the active taxonomy is rejected,
by design.
