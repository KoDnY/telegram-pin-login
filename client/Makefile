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
	$(MAKE) env

help:
	@echo make run      - Start Flet client
	@echo make install  - Install client dependencies and create missing .env
