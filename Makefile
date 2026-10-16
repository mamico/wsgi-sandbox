EXP ?= namedfile-range
RUN = uv run python

.PHONY: all venvs instances setup run clean

all: venvs instances setup run

venvs:
	$(RUN) -m wsgisandbox.envs venvs $(EXP)

instances:
	$(RUN) -m wsgisandbox.envs instances $(EXP)

setup:
	$(RUN) -m wsgisandbox.envs setup $(EXP)

run:
	$(RUN) experiments/$(EXP)/run.py $(ARGS)

clean:
	rm -rf variants/$(EXP) experiments/$(EXP)/results
