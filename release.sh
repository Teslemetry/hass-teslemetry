git fetch upstream dev
git rebase upstream/dev

script/setup

# Ask for version
echo "Enter the target version:"
read VERSION

git branch -D v$VERSION
git checkout -b v$VERSION

for PR_NUMBER in $(gh pr list --repo home-assistant/core --author Bre77 --state open --json number | jq -r '.[].number'); do
    PR_TITLE=$(gh pr view $PR_NUMBER --repo home-assistant/core --json title | jq -r '.title')
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
