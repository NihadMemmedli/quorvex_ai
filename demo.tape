# Quorvex AI Demo - Write tests in plain English, AI handles the rest
# Run with: vhs demo.tape

Output docs/assets/demo.gif
Output docs/assets/demo.webm

Set Shell zsh
Set FontSize 15
Set Width 1200
Set Height 700
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 50ms
Set PlaybackSpeed 1

# Show the spec
Sleep 500ms
Type "echo '📝 Step 1: Write your test in plain English'"
Enter
Sleep 1s
Type "cat specs/example-login.md"
Enter
Sleep 4s

# Show the generated test code
Type "echo '⚡ Step 2: AI generates production Playwright code'"
Enter
Sleep 1s
Type "cat tests/generated/example-login.spec.ts"
Enter
Sleep 5s

# Run the test
Type "echo '✅ Step 3: Run the generated test'"
Enter
Sleep 1s
Type "npx playwright test tests/generated/example-login.spec.ts --project=chromium --reporter=line"
Enter
Sleep 10s

Sleep 2s
