#!/bin/bash

while true
do
  git add .
  git commit -m "auto backup" || echo "no changes"
  git push
  sleep 300
done
