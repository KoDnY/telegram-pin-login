# GNU Make on Windows. Run from this folder or use make -C <folder>.
SHELL := cmd.exe
.SHELLFLAGS := /D /C
.DEFAULT_GOAL := help
PYTHON := .venv/Scripts/python.exe

.PHONY: help run start install env

run start:
	"$(PYTHON)" -u run.py

env:
	@if not exist .env copy /Y .env.example .env >nul

install:
	@if not exist ".venv/Scripts/python.exe" py -3.12 -m venv .venv
	"$(PYTHON)" -m pip install -r requirements.txt
	npm.cmd --prefix api ci
	$(MAKE) env

.PHONY: build test
build:
	npm.cmd --prefix api run build

test: build
	npm.cmd --prefix api test
	"$(PYTHON)" -m pytest bot/tests tests -q

help:
	@echo make run      - Start API, ngrok and Telegram bot
	@echo make install  - Install server dependencies and create missing .env
	@echo make build    - Build TypeScript API
	@echo make test     - Run API and Python tests
