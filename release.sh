TARGET="2025.4.0"

git fetch upstream $TARGET
git rebase upstream/$TARGET

# Ask for version
echo "Enter the target version (default: $TARGET):"
read NEW_TARGET
if [ ! -z "$NEW_TARGET" ]; then
    TARGET="$NEW_TARGET"
    git branch -D v$TARGET
    git checkout -b v$TARGET

    for PR in $(gh pr list --repo home-assistant/core --author Bre77 --state open --json number,title --jq '.[] | [.number, .title] | @tsv'); do
        PR_NUMBER=$(echo "$PR" | cut -f1)
        PR_TITLE=$(echo "$PR" | cut -f2)
        echo "Applying patch from PR #$PR_NUMBER: $PR_TITLE"
        curl -L https://github.com/home-assistant/core/pull/$PR_NUMBER.patch -o $PR_NUMBER.patch
        git apply -3 $PR_NUMBER.patch
        git mergetool
        rm *.patch
        git commit -am "#$PR_NUMBER: $PR_TITLE"
    done

    git tag -a v$TARGET -m "Release $TARGET"
    git push origin v$TARGET
    git checkout main
fi
