#!/bin/sh -x
pycodestyle $1
flake8 $1
pylint $1
