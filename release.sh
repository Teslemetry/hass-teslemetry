git fetch upstream dev
git rebase upstream/dev

script/setup

# Ask for version
echo "Enter the target version:"
read VERSION

git branch -D v$VERSION
git checkout -b v$VERSION

for PR in $(gh pr list --repo home-assistant/core --author Bre77 --state open --json number,title --jq '.[] | [.number, .title] | @tsv'); do
    PR_NUMBER=$(echo "$PR" | cut -f1)
    PR_TITLE=$(echo "$PR" | cut -f2)
    echo "Applying patch from PR #$PR_NUMBER: $PR_TITLE"
    curl -L https://github.com/home-assistant/core/pull/$PR_NUMBER.patch -o $PR_NUMBER.patch
    git apply -3 $PR_NUMBER.patch
    git mergetool
    rm *.patch
    git commit -am "#$PR_NUMBER: $PR_TITLE" --no-verify
done

yq -i -o json '.version="$VERSION"' "homeassistant/components/teslemetry/manifest.json"
git commit -am "v$VERSION" --no-verify

pytest tests/components/teslemetry

git tag -a v$VERSION -m "Release $VERSION"
git push origin v$VERSION
git checkout main
