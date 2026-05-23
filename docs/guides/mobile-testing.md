# Mobile Testing with Appium MCP

![Settings dashboard showing platform configuration and mobile testing health context](../assets/ui/settings.png)

<p class="caption">Settings dashboard showing platform configuration and mobile testing health context.</p>


Quorvex can run mobile smoke tests through Appium and exposes Appium MCP for AI-assisted mobile automation.

## Local iPhone Requirements

For real iPhone execution on macOS, install and select full Xcode:

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
xcodebuild -version
xcrun xctrace list devices
```

Connect and trust the iPhone, then confirm it is visible:

```bash
idevice_id -l
ideviceinfo -k DeviceName
```

Set WebDriverAgent signing values:

```bash
export IOS_TEAM_ID=YOUR_APPLE_TEAM_ID
export IOS_BUNDLE_ID_PREFIX=com.yourcompany.quorvex
export IOS_UDID=optional-device-udid
```

Start Appium:

```bash
npx appium driver install xcuitest
npx appium --use-drivers=xcuitest
```

## Run the Built-in Safari Smoke

```bash
python orchestrator/cli.py specs/mobile/iphone-safari-smoke.md \
  --target mobile \
  --platform ios \
  --appium-server-url http://127.0.0.1:4723
```

The run writes:

- `mobile_preflight.json`
- `appium-capabilities.json`
- `mobile_execution.log`
- generated JavaScript under `tests/mobile/`

## Capabilities

You can provide a capabilities file:

```json
{
  "ios": {
    "platformName": "iOS",
    "browserName": "Safari",
    "appium:automationName": "XCUITest",
    "appium:udid": "00008130-...",
    "appium:platformVersion": "17.5"
  }
}
```

Run with:

```bash
python orchestrator/cli.py specs/mobile/iphone-safari-smoke.md \
  --target mobile \
  --capabilities-file /absolute/path/to/capabilities.json
```
