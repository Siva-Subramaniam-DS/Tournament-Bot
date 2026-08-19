import sys

sys.stdout.reconfigure(encoding='utf-8')

# Let's map out each table in the modern schema (supabase_migration.sql) vs legacy (supabase_schema.sql) vs Python

tables_migration = {
    "GuildConfig": [
        "Guild_ID", "Admin_Role_ID", "Organizer_Role_ID", "Helper_Role_ID", "Judge_Role_ID", "Recorder_Role_ID", 
        "Staff_Role_ID", "Players_Role_ID", "Organization_Name", "Tournament_System_Name", "server_logo_path", 
        "server_logo_url", "Updated_At"
    ],
    "Tournaments": [
        "Tournament_ID", "Guild_ID", "Tournament_Name", "Game", "State", "Key", "Challonge_Bracket_Link", 
        "Google_Sheet_Link", "Attendance_Channel_ID", "Transcript_Channel_ID", "Schedule_Channel_ID", 
        "Result_Channel_ID", "Deadline_Channel_ID", "Closed_Ticket_Category_ID", "Auto_Room_Creation", 
        "Map_Pool", "Updated_At"
    ],
    "Deadlines": [
        "id", "Tournament_ID", "Round", "Deadline_Time", "Created_At"
    ],
    "Teams": [
        "Team_ID", "Tournament_ID", "Team_Name", "Captain_ID", "Captain_IGN", "Updated_At"
    ],
    "Players": [
        "Player_ID", "Team_ID", "Discord_ID", "IGN", "Game_ID", "Title", "Updated_At"
    ],
    "Matches": [
        "Match_ID", "Match_Name", "Tournament_ID", "Round", "Group", "Team1_ID", "Team2_ID", "Team1_Score", 
        "Team2_Score", "Status", "Scheduled_Time", "Channel_ID", "Poster_Path", "General_VOD", "Recorder_VOD", 
        "Judge_VOD", "recording_link", "recorder_link", "judge_link", "results_message_id", "results_channel_id", 
        "match_results_message_id", "match_results_channel_id", "Winner_ID", "Remarks", "Screenshots_Count", 
        "Disqualified", "Created_At", "Updated_At"
    ],
    "MatchStaff": [
        "id", "Match_ID", "User_ID", "Name", "Role", "Confirmed", "Confirmed_At", "Claimed_At"
    ],
    "StaffStats": [
        "id", "Guild_ID", "User_ID", "Name", "Judge_Count", "Recorder_Count", "Total_Count", "Timestamp"
    ]
}

tables_legacy_schema = {
    "GuildConfig": [
        "Guild_ID", "Admin_Role_ID", "Organizer_Role_ID", "Helper_Role_ID", "Judge_Role_ID", "Recorder_Role_ID", 
        "Staff_Role_ID", "Players_Role_ID", "organization_name", "tournament_system_name", "player_info_link", 
        "player_info_format", "player_info_participant_channel_id", "Updated_At", "Challonge_Role_ID", 
        "Challonge_Logs_Channel_ID", "Transcript_Logs_Channel_ID", "Closed_Category_ID", "Schedule_Channel_ID", 
        "Results_Channel_ID", "channel_bracket", "Bot_Logs_Channel_ID", "Thumbnail_Channel_ID", "google_sheet_link", 
        "sheetdb_api_url"
    ],
    "Tournaments": [
        "Guild_ID", "Tournament_ID", "Tournament_Name", "State", "Key", "challonge_bracket_link", 
        "Attendance_Channel_ID", "Transcript_Channel_ID", "Schedule_Channel_ID", "Rules_Channel_ID", 
        "Result_Channel_ID", "Deadline_Channel_ID", "Challonge_Logs_Channel_ID", "Transcript_Logs_Channel_ID", 
        "Bot_Logs_Channel_ID", "Closed_Ticket_Category_ID", "Closed_Ticket_Category_2_ID", "Open_Category_1_ID", 
        "Open_Category_2_ID", "Open_Category_3_ID", "Updated_At", "Captains_Sheet_Link", "Open_Category_4_ID", 
        "Auto_Room_Creation", "Players_Role_ID"
    ],
    "Events": [
        "id", "Guild_ID", "Timestamp", "Event_ID", "Match_Name", "Tournament", "Round", "Group", "Date", 
        "UTC_Time", "Team1_Captain_ID", "Team1_Captain_Name", "Team2_Captain_ID", "Team2_Captain_Name", 
        "Judge_ID", "Judge_Name", "Recorder_ID", "Recorder_Name", "Channel_ID", "Status", "recording_link", 
        "recorder_link", "judge_link", "results_message_id", "results_channel_id", "match_results_message_id", 
        "match_results_channel_id", "Created_By_ID", "Created_By_Name"
    ],
    "Results": [
        "id", "Guild_ID", "Timestamp", "Event_ID", "Match_Name", "Tournament", "Round", "Group", "Winner_ID", 
        "Winner_Name", "Winner_Score", "Loser_ID", "Loser_Name", "Loser_Score", "Judge_ID", "Judge_Name", 
        "Recorder_ID", "Recorder_Name", "Remarks", "Screenshots_Count", "Disqualified", "recording_link", 
        "recorder_link", "judge_link", "results_message_id", "results_channel_id"
    ],
    "Challonge_Uploads": [
        "id", "Guild_ID", "Timestamp", "Match_ID", "Winner_Participant_ID", "Winner_Score", "Loser_Score", 
        "Tournament_ID", "Uploaded_By_ID", "Uploaded_By_Name", "Status"
    ],
    "JudgeAssignments": [
        "id", "Guild_ID", "Timestamp", "Event_ID", "Judge_ID", "Judge_Name", "Tournament", "Round", "Date", 
        "UTC_Time", "Action"
    ],
    "StaffStats": [
        "id", "Guild_ID", "Timestamp", "User_ID", "Name", "Role_Updated", "Judge_Count", "Recorder_Count", "Total_Count"
    ],
    "Deadlines": [
        "id", "Guild_ID", "Round", "Deadline_Time", "Created_At"
    ]
}

# Python variables & keys used in main.py:
python_usage = {
    "GuildConfig": {
        "read": ["Admin_Role_ID", "Organizer_Role_ID", "Helper_Role_ID", "Judge_Role_ID", "Recorder_Role_ID", "Staff_Role_ID", "Players_Role_ID", "Challonge_Role_ID", "Challonge_Logs_Channel_ID", "Transcript_Logs_Channel_ID", "Closed_Category_ID", "Schedule_Channel_ID", "Results_Channel_ID", "channel_bracket", "Bot_Logs_Channel_ID", "Thumbnail_Channel_ID", "organization_name", "tournament_system_name", "google_sheet_link", "player_info_link", "player_info_format", "server_logo_path", "server_logo_url"],
        "write": ["Guild_ID", "Admin_Role_ID", "Organizer_Role_ID", "Helper_Role_ID", "Judge_Role_ID", "Recorder_Role_ID", "Staff_Role_ID", "Players_Role_ID", "Organization_Name", "Tournament_System_Name", "organization_name", "tournament_system_name", "server_logo_path", "server_logo_url", "google_sheet_link", "player_info_link", "player_info_format", "Updated_At"]
    },
    "Tournaments": {
        "read": ["Tournament_ID", "Guild_ID", "Tournament_Name", "State", "Game", "Key", "challonge_bracket_link", "Captains_Sheet_Link", "Sheet_Link", "Thumbnail_Channel_ID", "Attendance_Channel_ID", "Transcript_Channel_ID", "Schedule_Channel_ID", "Rules_Channel_ID", "Deadline_Channel_ID", "Result_Channel_ID", "Challonge_Logs_Channel_ID", "Transcript_Logs_Channel_ID", "Bot_Logs_Channel_ID", "Participant_Channel_ID", "Closed_Ticket_Category_ID", "Closed_Ticket_Category_2_ID", "Open_Category_1_ID", "Open_Category_2_ID", "Open_Category_3_ID", "Auto_Room_Creation", "Players_Role_ID"],
        "write": ["Tournament_ID", "Guild_ID", "Tournament_Name", "State", "Game", "Key", "Challonge_Bracket_Link", "Google_Sheet_Link", "Attendance_Channel_ID", "Transcript_Channel_ID", "Schedule_Channel_ID", "Rules_Channel_ID", "Result_Channel_ID", "Deadline_Channel_ID", "Bot_Logs_Channel_ID", "Challonge_Logs_Channel_ID", "Closed_Ticket_Category_ID", "Open_Category_1_ID", "Open_Category_2_ID", "Open_Category_3_ID", "Auto_Room_Creation", "Map_Pool", "Updated_At"]
    },
    "Deadlines": {
        "read": ["Guild_ID", "Round", "Deadline_Time"],
        "write": ["Guild_ID", "Round", "Deadline_Time"]
    },
    "Matches": {
        "read": ["Match_ID", "Tournament_ID"],
        "write": ["Match_ID", "Match_Name", "Tournament_ID", "Round", "Group", "Status", "Channel_ID", "recording_link", "recorder_link", "judge_link", "results_message_id", "results_channel_id", "match_results_message_id", "match_results_channel_id"]
    },
    "MatchStaff": {
        "read": ["Match_ID", "User_ID", "Role"],
        "write": ["Match_ID", "User_ID", "Name", "Role", "Confirmed"]
    },
    "StaffStats": {
        "read": [],
        "write": ["User_ID", "Guild_ID", "User_Name", "Name", "Judge_Count", "Recorder_Count", "Total_Count", "Last_Updated", "Timestamp"]
    },
    "Players": {
        "read": [],
        "write": ["IGN", "Game_ID", "Title", "Discord_ID"]
    },
    "Teams": {
        "read": [],
        "write": ["Team_Name", "Captain_ID"]
    }
}

print("Cross-checking completed.")
