#!/bin/sh

curl -X POST "http://localhost:8000/requirements/generate" \
  -H "Content-Type: application/json" \
  -d @sample_request.json
