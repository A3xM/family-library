#!/bin/bash
# Запуск Семейной библиотеки
# Использование: ./run.sh

set -e
cd "$(dirname "$0")"

echo "📚 Семейная библиотека"
echo "   http://localhost:8000"
echo ""

python3 app.py
