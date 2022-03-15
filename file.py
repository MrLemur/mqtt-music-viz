from time import sleep
import json
import paho.mqtt.client as mqtt
import pyaudio
import sys
import numpy as np
import aubio
from random import randint
from flask import Flask, redirect
from threading import Thread

app = Flask(__name__)

def convert_to_hex(value):
    array = value.split(",")
    return f"#{int(array[0]):02x}{int(array[1]):02x}{int(array[2]):02x}"


# Set up MQTT client
client = mqtt.Client()
client.connect("1.2.3.4", 1883)

colour = None


devices = [
    {"name": "livingroom", "topic": "cmnd/livingroom/Backlog", "type": "tasmota"},
    {
        "name": "led_strip",
        "topic": "zigbee2mqtt/LED Strip/set",
        "type": "zigbee",
    },
    {"name": "wled", "topic": "wled/5m/col", "colour": convert_to_hex(colour)},
]

colour_values = [
    {"colour": "dark red", "value": "174,0,0"},
    {"colour": "red", "value": "255,0,0"},
    {"colour": "orange-red", "value": "255,102,0"},
    {"colour": "yellow", "value": "255,239,0"},
    {"colour": "chartreuse", "value": "153,255,0"},
    {"colour": "lime", "value": "40,255,0"},
    {"colour": "aqua", "value": "0,255,242"},
    {"colour": "sky blue", "value": "0,122,255"},
    {"colour": "blue", "value": "5,0,255"},
    {"colour": "blue", "value": "71,0,237"},
    {"colour": "indigo", "value": "99,0,178"},
]

def get_device_config(type, colour):
    if type == "tasmota":
        if colour == "white":
            return (
                f"NoDelay;Fade 0;NoDelay;Speed 1;NoDelay;Power1 ON;NoDelay;CT 500"
            )
        else:
            return (
                f"NoDelay;Fade 0;NoDelay;Speed 1;NoDelay;Dimmer 100;NoDelay;Color2 {colour}"
            )
    if type == "zigbee":
        if colour == "white":
             return json.dumps(
            {
                "state": "ON",
                "brightness": 255,
                "transition": 0.001,
                "color_temp": "500"
            }
        )
        else:
             return json.dumps(
            {
                "state": "ON",
                "brightness": 255,
                "transition": 0.001,
                "color": {"rgb": colour},
            }
        )

def change_colour(value):

    number = randint(0, len(colour_values) - 1)
    return colour_values[number]


p = pyaudio.PyAudio()

BUFFER_SIZE = 1024
CHANNELS = 1
FORMAT = pyaudio.paFloat32
METHOD = "default"
SAMPLE_RATE = 44100
HOP_SIZE = BUFFER_SIZE // 2
PERIOD_SIZE_IN_FRAME = HOP_SIZE

mic_input = p.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=SAMPLE_RATE,
    input=True,
    frames_per_buffer=PERIOD_SIZE_IN_FRAME,
)

go = True 

def run():
    global go

    colour1 = "255,0,0"
    colour2 = "0,255,0"
    colour3 = "0,0,255"

    last_value = colour1


    tempo_detect = aubio.tempo(METHOD, BUFFER_SIZE, HOP_SIZE, SAMPLE_RATE)

    pitch_detect = aubio.pitch(METHOD, BUFFER_SIZE, HOP_SIZE, SAMPLE_RATE)
    pitch_detect.set_unit("Hz")
    pitch_detect.set_silence(-40)

    print("Listening to mic...")

    # Set variable for last colour used
    last_colour = ""

    while go:
        try:
            audio_buffer = mic_input.read(PERIOD_SIZE_IN_FRAME)
            samples = np.frombuffer(audio_buffer, dtype=aubio.float_type)

            # Detect a beat
            is_beat = tempo_detect(samples)

            # Get the pitch
            pitch = pitch_detect(samples)[0]

            # Get the volume
            volume = np.sum(samples ** 2) / len(samples)

            if is_beat[0]:
                print(pitch, volume)
                colour_dict = change_colour(pitch)
                while colour_dict["value"] == last_colour:
                    colour_dict = change_colour(pitch)
                colour = colour_dict["value"]
                # if pitch < 100:
                #     colour = "255,0,0"
                print(f"Setting colour to {colour}")
                for device in devices:
                    client.publish(
                        device["topic"], get_device_config(device["type"], colour)
                    )
                last_colour = colour

        except KeyboardInterrupt:
            print("*** Ctrl+C pressed, exiting")
            for device in devices:
                client.publish(
                    device["topic"], get_device_config(device["type"], "255,255,255")
                )
            break

@app.route('/start', methods=('GET','POST'))
def start():
    global go
    go = True
    thread = Thread(target=run)
    thread.start()
    return redirect('/')

@app.route('/stop', methods=('GET','POST'))
def stop():
    global go
    go = False
    for device in devices:
        client.publish(
            device["topic"], get_device_config(device["type"], "white")
        )
    return redirect('/')

@app.route('/', methods=('GET','POST'))
def index():
    return """
    <head>
  <meta content="width=device-width" name="viewport"/>
  <title>Lights Control</title>
 </head>
<body>
<a href="/start"><button style="border-radius: 10px; padding: 5px; width: 100%; font-size: 18pt;">Start</button></a><br />
<a href="/stop"><button style="border-radius: 10px; padding: 5px; width: 100%; font-size: 18pt;">Stop</button></a>
</body>
    """

app.run(host='0.0.0.0',debug=True)

mic_input.close()
p.terminate()