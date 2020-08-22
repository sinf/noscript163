#!/bin/bash

before=""
after=""

for webp in img/*.webp; do
	for ext in jpg png gif webp jpeg; do
		webp_bn=$(basename "$webp")
		org="img0/${webp_bn%%.webp}.${ext}"
		if [ -f "$org" ]; then
			before="$before $org"
			after="$after $webp"
			break
		fi
	done
done

echo "Before:"
du -ch $before|tail -n1

echo "After:"
du -ch $after|tail -n1

