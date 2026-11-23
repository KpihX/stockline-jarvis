.PHONY: all figures deck preview check build clean

all: build

check:
	sh scripts/check-dashes.sh slides/*.md
	uv run --with python-pptx --with matplotlib --with Pillow python scripts/render.py check

figures:
	uv run --with python-pptx --with matplotlib --with Pillow python scripts/render.py figures

deck:
	uv run --with python-pptx --with matplotlib --with Pillow python scripts/render.py deck

preview:
	uv run --with python-pptx --with matplotlib --with Pillow python scripts/render.py preview

build:
	sh scripts/check-dashes.sh slides/*.md
	uv run --with python-pptx --with matplotlib --with Pillow python scripts/render.py all --force

clean:
	rm -rf build/figs/* build/preview/*
