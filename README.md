# mqtt-musiz-viz

A simple Python script with Aubio to sync MQTT devices (Z2M, WLED, Tasmota) in time to music.

It is very rough and just been used personally.

You can edit the MQTT server to connect to, and add devices to the array (following the example of what's in there).

The colours picked are random, and it tries to uses the aubio beat detection to change colour.

There is a simple web server on port 80 to start and stop the effects.

It will sometimes get stuck and need to be forcefully restarted.