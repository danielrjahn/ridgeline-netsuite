.PHONY: install seed run reset smoke clean

install:
	pip install -r requirements.txt

seed:
	python -m app.seed

reset:
	python -m app.seed --reset

run:
	python -m app.main

smoke:
	python smoke.py

clean:
	rm -f minisuite.sqlite
