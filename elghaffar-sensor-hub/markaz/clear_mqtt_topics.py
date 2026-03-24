import paho.mqtt.client as mqtt

topics = []

def on_message(client, userdata, msg):
    topics.append(msg.topic)

client = mqtt.Client()
client.connect("localhost", 1883, 60)
client.subscribe("#")
client.on_message = on_message

client.loop_start()
import time; time.sleep(2)  # Let it gather retained topics
client.loop_stop()

# Clear each topic
for t in set(topics):
    client.publish(t, payload=None, retain=True)
    print("Cleared:", t)
