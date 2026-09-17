# Test resign logic simulation
scheduled_events = {
    "test_event_1": {
        "guild_id": "123",
        "judge": 999,
        "recorder": 999,
        "round": "R1",
        "date_str": "Today",
        "time_str": "12:00",
        "tournament": "Championship"
    }
}

user_id = 999
user_events = []

for event_id, event_data in scheduled_events.items():
    judge_val = event_data.get('judge')
    recorder_val = event_data.get('recorder')

    is_judge = False
    if judge_val:
        if str(getattr(judge_val, 'id', judge_val)) == str(user_id):
            is_judge = True

    is_recorder = False
    if recorder_val:
        if str(getattr(recorder_val, 'id', recorder_val)) == str(user_id):
            is_recorder = True

    if is_judge:
        user_events.append((event_id, event_data, "Judge"))
    if is_recorder:
        user_events.append((event_id, event_data, "Recorder"))

print("Events found for user:", len(user_events))
for ev_id, ev_data, role in user_events:
    print(f"- Role: {role}, Event: {ev_id}")

assert len(user_events) == 2, "Expected 2 options (Judge and Recorder)!"
assert user_events[0][2] == "Judge"
assert user_events[1][2] == "Recorder"
print("SUCCESS: Both Judge and Recorder options correctly generated!")
