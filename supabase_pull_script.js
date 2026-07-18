/**
 * Google Apps Script: Pull Supabase Tables to Google Sheet Tabs (100% Free)
 * 
 * INSTRUCTIONS:
 * 1. Open your Google Sheet.
 * 2. Click on "Extensions" -> "Apps Script" in the top menu.
 * 3. Delete any existing default code and paste this entire script.
 * 4. Fill in the CONFIGURATION variables below (SUPABASE_URL and SUPABASE_KEY).
 *    - You can find these in your Supabase project settings under API.
 * 5. Update the TABLES_TO_SYNC list to match your database table names and Sheet tab names.
 * 6. Save (Ctrl+S) and refresh your Google Sheet.
 * 7. You will see a new menu item "Supabase Sync" next to "Help" in Google Sheets.
 *    - Click "Supabase Sync" -> "Setup Auto-Timer (10 mins)" to run this automatically in the background.
 */

// =========================================================================
// 1. CONFIGURATION (Set these to match your Supabase project credentials)
// =========================================================================
var SUPABASE_URL = "https://your-project-id.supabase.co"; 
var SUPABASE_KEY = "your-anon-key-or-service-role-key";

// List of mappings: { supabaseTable: "SupabaseTableName", sheetTab: "SheetTabName" }
var TABLES_TO_SYNC = [
  { supabaseTable: "GuildConfig", sheetTab: "GuildConfig" },
  { supabaseTable: "Tournaments", sheetTab: "Tournaments" },
  { supabaseTable: "Results", sheetTab: "Results" },
  { supabaseTable: "Events", sheetTab: "Events" },
  { supabaseTable: "StaffStats", sheetTab: "Staff Leaderboard" },
  { supabaseTable: "JudgeAssignments", sheetTab: "Judge Assignments" }
];

// =========================================================================
// 2. CUSTOM MENU SETUP
// Adds a menu button to your Sheet upon load/refresh
// =========================================================================
function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu('Supabase Sync')
    .addItem('Pull All Data from Supabase', 'pullAllTables')
    .addItem('Setup Auto-Timer (10 mins)', 'createTimeTrigger')
    .addToUi();
}

// =========================================================================
// 3. MAIN PULL LOGIC
// Fetches records from Supabase and overwrites Google Sheet tabs
// =========================================================================
function pullAllTables() {
  TABLES_TO_SYNC.forEach(function(mapping) {
    try {
      pullSupabaseTableToSheet(mapping.supabaseTable, mapping.sheetTab);
    } catch (e) {
      Logger.log("❌ Error syncing " + mapping.supabaseTable + ": " + e.toString());
    }
  });
}

function pullSupabaseTableToSheet(tableName, tabName) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(tabName);
  
  // Create the sheet tab if it doesn't exist
  if (!sheet) {
    sheet = ss.insertSheet(tabName);
  }
  
  // Fetch data from Supabase REST API (PostgREST)
  var url = SUPABASE_URL + "/rest/v1/" + tableName + "?select=*";
  var headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": "Bearer " + SUPABASE_KEY,
    "User-Agent": "PostgREST-Client"
  };
  
  var options = {
    "method": "get",
    "headers": headers,
    "muteHttpExceptions": true
  };
  
  var response = UrlFetchApp.fetch(url, options);
  var responseCode = response.getResponseCode();
  
  if (responseCode !== 200) {
    throw new Error("Supabase returned HTTP " + responseCode + ": " + response.getContentText());
  }
  
  var data = JSON.parse(response.getContentText());
  if (!data || data.length === 0) {
    Logger.log("ℹ️ Table '" + tableName + "' is empty.");
    return;
  }
  
  // Clear the existing sheet content completely
  sheet.clear();
  
  // Get all columns (headers) from the first row keys
  var headersList = Object.keys(data[0]);
  
  // Prepare a 2D array for writing (Row 1 is headers)
  var sheetValues = [];
  sheetValues.push(headersList); 
  
  data.forEach(function(row) {
    var rowValues = headersList.map(function(header) {
      var val = row[header];
      if (val === null || val === undefined) {
        return "";
      }
      // If it's an object or array, store it as a stringified representation
      if (typeof val === 'object') {
        return JSON.stringify(val);
      }
      return val;
    });
    sheetValues.push(rowValues);
  });
  
  // Write the values to the sheet range
  sheet.getRange(1, 1, sheetValues.length, headersList.length).setValues(sheetValues);
  Logger.log("✅ Successfully pulled " + data.length + " rows from Supabase table '" + tableName + "' to Sheet tab '" + tabName + "'");
}

// =========================================================================
// 4. AUTOMATIC TIME TRIGGER SETUP
// Clears duplicate triggers and registers a new 10-minute recurring sync
// =========================================================================
function createTimeTrigger() {
  // Clear existing triggers to prevent stacking
  var triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(function(t) {
    if (t.getHandlerFunction() === 'pullAllTables') {
      ScriptApp.deleteTrigger(t);
    }
  });
  
  // Create a new time-driven trigger to run every 10 minutes
  ScriptApp.newTrigger('pullAllTables')
    .timeBased()
    .everyMinutes(10)
    .create();
  
  try {
    SpreadsheetApp.getUi().alert("✅ Timer Trigger Configured!\nThe sheet will now pull data from Supabase automatically every 10 minutes in the background.");
  } catch (e) {
    Logger.log("✅ Timer Trigger Configured! (Running in background)");
  }
}
