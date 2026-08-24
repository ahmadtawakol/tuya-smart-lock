# Live verification checklist

Use this checklist with a supported lock in a controlled setting. It contains no
credentials or device identifiers and must stay that way.

## Safety and account preparation

- [ ] Keep an authorized person at the door, preserve a physical entry method,
      and avoid testing when a failed lock or unlock could strand someone.
- [ ] Configure Home Assistant's official **Tuya** integration using the User
      Code and QR-code login from the Tuya or Smart Life app.
- [ ] Confirm the target lock appears in the official Tuya integration, even if
      it is marked unsupported or exposes no entities there.
- [ ] Enable both remote locking and password-free remote unlock/remote control
      in the mobile app.
- [ ] Confirm manual lock and unlock still work before testing cloud commands.

## Install and initial state

- [ ] Copy `custom_components/tuya_smart_lock` into the Home Assistant config
      directory, restart Home Assistant, and add **Tuya Smart Lock** from the UI.
- [ ] Select the lock discovered through the official Tuya integration.
- [ ] Confirm the integration loads without warnings or repeated retries.
- [ ] Confirm all expected entities are available.
- [ ] Compare the lock entity's locked/unlocked state with the physical door.
- [ ] Compare the battery sensor with the Tuya Smart or Smart Life app.
- [ ] Open the camera entity and record whether it returns the outside lens,
      inside lens, a composite image, or no stream.
- [ ] Take one on-demand snapshot into a private allowlisted directory and
      confirm the temporary stream URL never appears in state or logs.
- [ ] Confirm a missing or malformed datapoint becomes unknown instead of a
      misleading state, if this can be observed without modifying the device.

## Commands and physical activity

- [ ] Physically unlock the lock, wait through a polling interval, and confirm
      Home Assistant reports unlocked.
- [ ] Physically lock it, wait through a polling interval, and confirm Home
      Assistant reports locked.
- [ ] From a safe position with door access preserved, issue **Lock** in Home
      Assistant first and confirm both physical movement and the final entity
      state. If it is rejected or times out, record that free control is not
      supported and do not proceed to unlock testing.
- [ ] Only after locking succeeds, issue **Unlock** while an authorized person
      remains beside the door and confirm both physical movement and final state.
- [ ] Verify an inside-open action emits the **Opened inside** event.
- [ ] Ring the doorbell and verify a **Doorbell** `ring` event.
- [ ] Trigger a private `camera.snapshot` automation from a doorbell event and
      confirm the resulting image corresponds to the event time.
- [ ] Trigger only a safe, documented alarm condition and verify the **Lock
      alarm** event and sanitized reason, if supported by the device.

## Unlock telemetry

Exercise only credentials already approved for the test lock. Confirm the
**Unlocked** entity reports the appropriate event type for each supported method:

- [ ] Password or PIN.
- [ ] Fingerprint.
- [ ] Card or badge.
- [ ] Face recognition.
- [ ] Phone-remote unlock.

If Home Assistant exposes a numeric `credential_id`, verify only that it is
stable enough for the intended automation. Do not paste or publish the value.

## Replay, failure, and recovery

- [ ] Restart Home Assistant after the latest events and verify historical Tuya
      shadow values are not replayed as new events.
- [ ] Reload the integration and verify historical events are not replayed.
- [ ] Where safe, cause a temporary network or official-Tuya failure and confirm
      entities become unavailable without exposing sensitive payloads.
- [ ] Restore connectivity and confirm the integration and entity availability
      recover on a later refresh.
- [ ] If safe to simulate, confirm an accepted but physically unconfirmed
      command reports an error rather than assuming success.

## Sanitized evidence

- [ ] Record Home Assistant version, integration version, device category/model,
      command direction, timestamps, expected result, and observed result.
- [ ] Capture sanitized diagnostics and only the minimum relevant log lines.
- [ ] Remove access IDs, access secrets, tokens, account/device IDs, credential
      IDs, credential payloads, QR codes, and raw Tuya responses.
- [ ] Never paste secrets, tickets, or credential payloads into an issue, chat,
      screenshot, filename, or automation trace.

Camera/video streaming, on-screen display (OSD), password or credential
management, and other device administration are outside this checklist and the
integration's scope.
