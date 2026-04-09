#!/bin/sh
cd /app
echo "Checking dependencies..."
if [ ! -d "/app/node_modules/recharts" ] || [ "$(md5sum /app/package.json | awk '{print $1}')" != "$(cat /app/.package.json.md5 2>/dev/null || echo '')" ]; then
    echo "Installing dependencies..."
    npm config set registry https://registry.npmmirror.com && npm install
    md5sum /app/package.json | awk '{print $1}' > /app/.package.json.md5
fi
echo "Starting development server..."
npx next dev -H 0.0.0.0 -p 3000 --webpack
2025/5/3 - 2025/7/9