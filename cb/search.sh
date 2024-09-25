#!/usr/bin/env bash
IFS=',' read -ra words <<< "$1"   # Split comma-separated words into an array
for word in "${words[@]}"; do
    grep -inE "(^|[^[:alnum:]_-\t,])((_|;|-)?($word)(_|;|-)?)(\b|[^[:alnum:]_-\t,])" "$2" | awk -v word="$word" '{print word ": " $0}'
    #grep -inE "(^|[^[:alnum:]_-])(($word)(_|;|-)?)(\b|[^[:alnum:]_-])" "$2" | awk -v word="$word" '{print word ": " $0}'      # Search for each word case-insensitively
    #grep -inE "(^|[^[:alnum:]_-])($word(_|-|\.| |;|\t|,|$))" "$2" | awk -v word="$word" '{print word ": " $0}'
done

# bash /app/cb/search.sh mapk3 /app/media/user_files/different_2.txt