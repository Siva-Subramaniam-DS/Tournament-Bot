/**
 * Google Apps Script: Sync Google Sheet rows to Supabase with custom Header Mapping
 * 
 * INSTRUCTIONS:
 * 1. Open your Google Sheet.
 * 2. Click on "Extensions" -> "Apps Script" in the top menu.
 * 3. Delete any existing default code and paste this entire script.
 * 4. Update the CONFIGURATION variables below (SUPABASE_URL, SUPABASE_KEY, TABLE_NAME).
 * 5. Update the HEADER_MAP object to match your exact Google Sheet headers to Supabase column names.
 * 6. Save (Ctrl+S) and refresh your Google Sheet.
 * 7. You will see a new menu item "Supabase Sync" next to "Help". Click "Sync Current Sheet to Supabase".
 * 8. Authorize the script on first run.
 */

// =========================================================================
// 1. CONFIGURATION (Modify these to match your Supabase project)
// =========================================================================
const SUPABASE_URL = "https://your-project-id.supabase.co";
const SUPABASE_KEY = "your-service-role-key-or-anon-key"; // service-role key is recommended if RLS is enabled
const TABLE_NAME = "Your_Supabase_Table_Name"; // e.g., "Tournaments" or "GuildConfig" or "Players"

// =========================================================================
// 2. HEADER MAPPING
// Format: "Google Sheet Header Name": "supabase_column_name"
//
// - Keys (left) MUST match the exact text in your Google Sheet's first row.
// - Values (right) MUST match the exact column names in your Supabase table.
// =========================================================================
const HEADER_MAP = {
  // --- Example Mappings (Modify these to match your actual columns) ---
  "Team Name": "Team_Name",
  "Captain Discord ID": "Captain_ID",
  "Captain Game Name": "Captain_IGN",
  "Player Discord ID": "Discord_ID",
  "Player Game Name": "IGN",
  "Player Game ID": "Game_ID",
  "Player Title": "Title"
};

// =========================================================================
// 3. CUSTOM MENU SETUP
// Adds a menu button to your Sheet upon load/refresh
// =========================================================================
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('Supabase Sync')
    .addItem('Sync Current Sheet to Supabase', 'syncSheetToSupabase')
    .addToUi();
}

// =========================================================================
// 4. MAIN SYNC LOGIC
// Reads Sheet, maps headers, formats JSON, and updates Supabase
// =========================================================================
function syncSheetToSupabase() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const dataRange = sheet.getDataRange();
  const values = dataRange.getValues();
  
  if (values.length < 2) {
    SpreadsheetApp.getUi().alert("Error: The sheet is empty or contains no data rows.");
    return;
  }
  
  // Extract headers from the first row and sanitize whitespace
  const sheetHeaders = values[0].map(h => h.toString().trim());
  const rows = values.slice(1);
  
  const payloadData = [];
  
  // Iterate through all data rows in the spreadsheet
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const rowObject = {};
    let hasData = false;
    
    for (let j = 0; j < sheetHeaders.length; j++) {
      const header = sheetHeaders[j];
      const cellValue = row[j];
      
      // Look up if this header has a mapping to a Supabase column
      const supabaseColumn = HEADER_MAP[header];
      
      if (supabaseColumn) {
        let formattedValue = cellValue;
        
        // Convert to string and clean up if it's text
        if (typeof cellValue === 'string') {
          formattedValue = cellValue.trim();
        }
        
        // Extract raw number if Discord ID is parsed as an exponential float or standard float
        if (supabaseColumn.toLowerCase().includes("id") && typeof cellValue === 'number') {
          formattedValue = cellValue.toFixed(0); // Prevents float notation (e.g. 1.23e+17 -> 123000000000000000)
        }
        
        rowObject[supabaseColumn] = formattedValue;
        
        if (formattedValue !== "") {
          hasData = true;
        }
      }
    }
    
    // Only push rows that have actual data
    if (hasData) {
      payloadData.push(rowObject);
    }
  }
  
  if (payloadData.length === 0) {
    SpreadsheetApp.getUi().alert("No valid data rows found matching the mapping configuration.");
    return;
  }
  
  // Send the formatted payload to Supabase REST API (PostgREST)
  try {
    const url = `${SUPABASE_URL}/rest/v1/${TABLE_NAME}`;
    
    // Build Headers
    // Prefer: resolution=merge-duplicates ensures an UPSERT behaves correctly if there's a primary key/unique constraint
    const headers = {
      "apikey": SUPABASE_KEY,
      "Authorization": `Bearer ${SUPABASE_KEY}`,
      "Content-Type": "application/json",
      "Prefer": "resolution=merge-duplicates" 
    };
    
    const options = {
      "method": "post",
      "headers": headers,
      "payload": JSON.stringify(payloadData),
      "muteHttpExceptions": true
    };
    
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();
    
    if (responseCode >= 200 && responseCode < 300) {
      SpreadsheetApp.getUi().alert(`✅ Success!\n\nSynced ${payloadData.length} records to Supabase table '${TABLE_NAME}'.`);
    } else {
      SpreadsheetApp.getUi().alert(`❌ Supabase Error (HTTP ${responseCode}):\n\n${responseText}`);
    }
  } catch (error) {
    SpreadsheetApp.getUi().alert(`❌ Script Execution Error:\n\n${error.toString()}`);
  }
}
