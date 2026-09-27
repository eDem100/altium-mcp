// altium_bridge.pas
// This script acts as a bridge between the MCP server and Altium
// It reads commands from a request JSON file, executes them, and writes results to a response JSON file

const
	constScriptProjectName = 'Altium_API'; // Define the script project name
    REPLACEALL = 1;
var
    RequestData : TStringList;
    ResponseData : TStringList;
    Params : TStringList;
	REQUEST_FILE : String;
    RESPONSE_FILE : String;
    ROOT_DIR: String;
    PilotRequestId: String;
    PilotContext: String;

{..............................................................................}
{ Initialize file paths using a fixed exchange directory.                      }
{ Both the Python MCP server and this script independently resolve to          }
{ C:\Users\Public\altium_mcp\ — avoiding fragile script-project-path          }
{ resolution that breaks when Altium caches stale script projects.             }
{..............................................................................}
procedure InitializeFilePaths();
begin
    ROOT_DIR := 'C:\AltiumBridge\private-exchange\';

    // The installer creates and protects this exact exchange directory.

    // Set the file paths
    REQUEST_FILE := ROOT_DIR + 'request.json';
    RESPONSE_FILE := ROOT_DIR + 'response.json';
end;

// Bounded diagnostic trace: stages only, never design data or request values.
procedure PilotTrace(Stage: String);
var TraceLines: TStringList;
begin
    TraceLines := TStringList.Create;
    try
        TraceLines.Add('stage=' + Stage);
        TraceLines.Add('request_id_length=' + IntToStr(Length(PilotRequestId)));
        TraceLines.SaveToFile(ROOT_DIR + 'native-trace.txt');
    finally
        TraceLines.Free;
    end;
end;

// Extract the component pins logic
function ExecuteGetComponentPins(RequestData: TStringList): String;
var
    ParamValue: String;
    i: Integer;
    DesignatorsList: TStringList;
begin
    DesignatorsList := TStringList.Create;
    try
        // Look through all the RequestData lines to find designators
        for i := 0 to RequestData.Count - 1 do
        begin
            if (Pos('"designators"', RequestData[i]) > 0) then
            begin
                // Found the designators parameter
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')
                
                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    // This is an array element
                    // Extract the designator value
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);
                    
                    if (ParamValue <> '') and (ParamValue <> '[') then
                        DesignatorsList.Add(ParamValue);
                    
                    i := i + 1;
                end;
                
                break;
            end;
        end;
        
        if DesignatorsList.Count > 0 then
        begin
            Result := GetComponentPinsFromList(ROOT_DIR, DesignatorsList);
        end
        else
        begin
            Result := '';
        end;
    finally
        DesignatorsList.Free;
    end;
end;

// Extract the create net class logic
function ExecuteCreateNetClass(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    ComponentName: String;
    SourceList: TStringList;
begin
    ComponentName := '';
    SourceList := TStringList.Create;
    
    try
        // Parse parameters from the request
        for i := 0 to RequestData.Count - 1 do
        begin
            // Look for class_name
            if (Pos('"class_name"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ComponentName := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ComponentName := TrimJSON(ComponentName);
            end
            // Look for net_names array
            else if (Pos('"net_names"', RequestData[i]) > 0) then
            begin
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')
                
                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    // Extract the net name
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);
                    
                    if (ParamValue <> '') and (ParamValue <> '[') then
                        SourceList.Add(ParamValue);
                    
                    i := i + 1;
                end;
            end;
        end;
        
        if (ComponentName <> '') and (SourceList.Count > 0) then
        begin
            Result := CreateNetClass(ComponentName, SourceList);
        end
        else
        begin
            if ComponentName = '' then
                Result := '{"success": false, "error": "No class name provided"}'
            else
                Result := '{"success": false, "error": "No net names provided"}';
        end;
    finally
        SourceList.Free;
    end;
end;

// Extract the take view screenshot logic
function ExecuteTakeViewScreenshot(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    ViewType: String;
    DesignatorsList: TStringList;
begin
    // Extract the view type parameter
    ViewType := 'pcb';  // Default to PCB
    DesignatorsList := TStringList.Create;

    try
        // Parse parameters from the request
        for i := 0 to RequestData.Count - 1 do
        begin
            // Look for view_type parameter
            if (Pos('"view_type"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ParamValue := TrimJSON(ParamValue);
                ViewType := ParamValue;
            end
            // Look for optional designators array to zoom to before capture
            else if (Pos('"designators"', RequestData[i]) > 0) then
            begin
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')

                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);

                    if (ParamValue <> '') and (ParamValue <> '[') then
                        DesignatorsList.Add(ParamValue);

                    i := i + 1;
                end;
            end;
        end;

        Result := TakeViewScreenshot(ViewType, DesignatorsList);
    finally
        DesignatorsList.Free;
    end;
end;

// Extract the create schematic symbol logic
function ExecuteCreateSchematicSymbol(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    ComponentName: String;
    PartCount: Integer;
    PinsList: TStringList;
    GraphicsList: TStringList;
begin
    // Look for component name
    ComponentName := '';
    PartCount := 1;  // Default to single-part symbol
    PinsList := TStringList.Create;
    GraphicsList := TStringList.Create;

    try
        // Parse parameters from the request
        for i := 0 to RequestData.Count - 1 do
        begin
            // Look for component name
            if (Pos('"symbol_name"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ComponentName := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ComponentName := TrimJSON(ComponentName);
            end
            // Look for part_count
            else if (Pos('"part_count"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ParamValue := TrimJSON(ParamValue);
                PartCount := StrToInt(ParamValue);
            end
            // Look for pins array
            else if (Pos('"pins"', RequestData[i]) > 0) then
            begin
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')

                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    // Extract the pin data
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);
                    // Unescape JSON backslashes (e.g. \\ -> \ for Altium overbar notation)
                    ParamValue := StringReplace(ParamValue, '\\', '\', REPLACEALL);

                    if (ParamValue <> '') and (ParamValue <> '[') then
                        PinsList.Add(ParamValue);

                    i := i + 1;
                end;
            end
            // Look for graphics array
            else if (Pos('"graphics"', RequestData[i]) > 0) then
            begin
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')

                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);

                    if (ParamValue <> '') and (ParamValue <> '[') then
                        GraphicsList.Add(ParamValue);

                    i := i + 1;
                end;
            end
            // Look for description
            else if (Pos('"description"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ParamValue := TrimJSON(ParamValue);
                PinsList.Add('Description=' + ParamValue);
            end;
        end;

        if ComponentName <> '' then
        begin
            Result := CreateSchematicSymbol(ComponentName, PinsList, GraphicsList, PartCount);
        end
        else
        begin
            Result := '';
        end;
    finally
        PinsList.Free;
        GraphicsList.Free;
    end;
end;

// Extract the set PCB layer visibility logic
function ExecuteSetPCBLayerVisibility(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    SourceList: TStringList;
    Visible: Boolean;
begin
    // Create a stringlist for layer names and extract the visible parameter
    SourceList := TStringList.Create;
    Visible := False;
    
    try
        // Parse parameters from the request
        for i := 0 to RequestData.Count - 1 do
        begin
            // Look for layer_names array
            if (Pos('"layer_names"', RequestData[i]) > 0) then
            begin
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')
                
                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    // Extract the layer name
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);
                    
                    if (ParamValue <> '') and (ParamValue <> '[') then
                        SourceList.Add(ParamValue);
                    
                    i := i + 1;
                end;
            end
            // Look for visible parameter
            else if (Pos('"visible"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ParamValue := TrimJSON(ParamValue);
                Visible := (ParamValue = 'true');
            end;
        end;
        
        if SourceList.Count > 0 then
        begin
            Result := SetPCBLayerVisibility(SourceList, Visible);
        end
        else
        begin
            Result := '{"success": false, "error": "No layer names provided"}';
        end;
    finally
        SourceList.Free;
    end;
end;

// Extract the set component position logic
function ExecuteSetComponentPosition(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    Designator: String;
    NewX, NewY: Float;
    Rotation: Float;
begin
    Designator := '';
    NewX := 0;
    NewY := 0;
    Rotation := -1;  // Default -1 means keep current rotation
    
    try
        // Parse parameters from the request
        for i := 0 to RequestData.Count - 1 do
        begin
            // Look for designator
            if (Pos('"designator"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ParamValue := TrimJSON(ParamValue);
                ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                Designator := Trim(ParamValue);
            end
            // Look for x
            else if (Pos('"x"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ParamValue := TrimJSON(ParamValue);
                NewX := SafeStrToFloat(ParamValue);
            end
            // Look for y
            else if (Pos('"y"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ParamValue := TrimJSON(ParamValue);
                NewY := SafeStrToFloat(ParamValue);
            end
            // Look for rotation
            else if (Pos('"rotation"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ParamValue := TrimJSON(ParamValue);
                Rotation := SafeStrToFloat(ParamValue);
            end;
        end;
        
        if Designator <> '' then
        begin
            Result := SetComponentPosition(Designator, NewX, NewY, Rotation);
        end
        else
        begin
            Result := '';
        end;
    finally
    end;
end;

// Extract the move components logic
function ExecuteMoveComponents(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    DesignatorsList: TStringList;
    XOffset, YOffset: Integer;
    Rotation: Float;
begin
    // For this command, we need to extract the designators array and the offset values
    DesignatorsList := TStringList.Create;
    XOffset := 0;
    YOffset := 0;
    Rotation := 0;  // Default rotation is 0 (no change)
    
    try
        // Parse parameters from the request
        for i := 0 to RequestData.Count - 1 do
        begin
            // Look for designators array
            if (Pos('"designators"', RequestData[i]) > 0) then
            begin
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')
                
                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    // Extract the designator value
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);
                    
                    if (ParamValue <> '') and (ParamValue <> '[') then
                        DesignatorsList.Add(ParamValue);
                    
                    i := i + 1;
                end;
            end
            // Look for x_offset
            else if (Pos('"x_offset"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ParamValue := TrimJSON(ParamValue);
                XOffset := MilsToCoord(SafeStrToFloat(ParamValue));
            end
            // Look for y_offset
            else if (Pos('"y_offset"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ParamValue := TrimJSON(ParamValue);
                YOffset := MilsToCoord(SafeStrToFloat(ParamValue));
            end
            // Look for rotation
            else if (Pos('"rotation"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ParamValue := TrimJSON(ParamValue);
                Rotation := SafeStrToFloat(ParamValue);
            end;
        end;
        
        if DesignatorsList.Count > 0 then
        begin
            Result := MoveComponentsByDesignators(DesignatorsList, XOffset, YOffset, Rotation);
        end
        else
        begin
            Result := '';
        end;
    finally
        DesignatorsList.Free;
    end;
end;

// Extract the get footprint primitives logic
function ExecuteGetFootprintPrimitives(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    LibraryPath: String;
    FootprintName: String;
begin
    LibraryPath := '';
    FootprintName := '';

    for i := 0 to RequestData.Count - 1 do
    begin
        if (Pos('"library_path"', RequestData[i]) > 0) then
        begin
            ValueStart := Pos(':', RequestData[i]) + 1;
            ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
            LibraryPath := TrimJSON(ParamValue);
        end
        else if (Pos('"footprint_name"', RequestData[i]) > 0) then
        begin
            ValueStart := Pos(':', RequestData[i]) + 1;
            ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
            FootprintName := TrimJSON(ParamValue);
        end;
    end;

    Result := GetFootprintPrimitives(ROOT_DIR, LibraryPath, FootprintName);
end;

// Extract the create footprints batch logic
function ExecuteCreateFootprintsBatch(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    SpecFile: String;
begin
    SpecFile := '';

    for i := 0 to RequestData.Count - 1 do
    begin
        if (Pos('"spec_file"', RequestData[i]) > 0) then
        begin
            ValueStart := Pos(':', RequestData[i]) + 1;
            ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
            SpecFile := TrimJSON(ParamValue);
        end;
    end;

    if (SpecFile <> '') then
        Result := CreateFootprintsBatch(SpecFile)
    else
        Result := 'ERROR: No spec_file provided for create_footprints_batch';
end;

// Extract the create symbols batch logic
function ExecuteCreateSymbolsBatch(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    SpecFile: String;
begin
    SpecFile := '';

    // Parse parameters from the request
    for i := 0 to RequestData.Count - 1 do
    begin
        if (Pos('"spec_file"', RequestData[i]) > 0) then
        begin
            ValueStart := Pos(':', RequestData[i]) + 1;
            ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
            ParamValue := TrimJSON(ParamValue);
            SpecFile := ParamValue;
        end;
    end;

    if (SpecFile <> '') then
        Result := CreateSymbolsBatch(SpecFile)
    else
        Result := 'ERROR: No spec_file provided for create_symbols_batch';
end;

// Extract the get symbol primitives logic
function ExecuteGetSymbolPrimitives(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    LibraryPath: String;
    SymbolName: String;
begin
    LibraryPath := '';
    SymbolName := '';

    // Parse parameters from the request
    for i := 0 to RequestData.Count - 1 do
    begin
        // Look for library_path
        if (Pos('"library_path"', RequestData[i]) > 0) then
        begin
            ValueStart := Pos(':', RequestData[i]) + 1;
            ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
            ParamValue := TrimJSON(ParamValue);
            LibraryPath := ParamValue;
        end
        // Look for symbol_name
        else if (Pos('"symbol_name"', RequestData[i]) > 0) then
        begin
            ValueStart := Pos(':', RequestData[i]) + 1;
            ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
            ParamValue := TrimJSON(ParamValue);
            SymbolName := ParamValue;
        end;
    end;

    Result := GetSymbolPrimitives(ROOT_DIR, LibraryPath, SymbolName);
end;

// Extract the get net connections logic
function ExecuteGetNetConnections(RequestData: TStringList): String;
var
    ParamValue: String;
    i: Integer;
    DesignatorsList: TStringList;
begin
    DesignatorsList := TStringList.Create;

    try
        // Parse parameters from the request
        for i := 0 to RequestData.Count - 1 do
        begin
            // Look for designators array (optional - empty means use selection)
            if (Pos('"designators"', RequestData[i]) > 0) then
            begin
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')

                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);

                    if (ParamValue <> '') and (ParamValue <> '[') then
                        DesignatorsList.Add(ParamValue);

                    i := i + 1;
                end;
            end;
        end;

        Result := GetNetConnections(ROOT_DIR, DesignatorsList);
    finally
        DesignatorsList.Free;
    end;
end;

// Extract the check placement logic
function ExecuteCheckPlacement(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    DesignatorsList: TStringList;
    ClearanceMils: Double;
begin
    DesignatorsList := TStringList.Create;
    ClearanceMils := 6;

    try
        // Parse parameters from the request
        for i := 0 to RequestData.Count - 1 do
        begin
            // Look for designators array (optional - empty means use selection)
            if (Pos('"designators"', RequestData[i]) > 0) then
            begin
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')

                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);

                    if (ParamValue <> '') and (ParamValue <> '[') then
                        DesignatorsList.Add(ParamValue);

                    i := i + 1;
                end;
            end
            // Look for clearance_mils
            else if (Pos('"clearance_mils"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
                ParamValue := TrimJSON(ParamValue);
                ClearanceMils := SafeStrToFloat(ParamValue);
            end;
        end;

        Result := CheckPlacement(DesignatorsList, ClearanceMils);
    finally
        DesignatorsList.Free;
    end;
end;

// Extract the place components logic
function ExecutePlaceComponents(RequestData: TStringList): String;
var
    ParamValue: String;
    i: Integer;
    PlacementsList: TStringList;
begin
    // Placements arrive as an array of pipe-delimited strings
    // ('Designator|X|Y|Rotation|Layer') so the line-based parser stays robust
    PlacementsList := TStringList.Create;

    try
        // Parse parameters from the request
        for i := 0 to RequestData.Count - 1 do
        begin
            // Look for placements array
            if (Pos('"placements"', RequestData[i]) > 0) then
            begin
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')

                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    // Extract the placement value
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);

                    if (ParamValue <> '') and (ParamValue <> '[') then
                        PlacementsList.Add(ParamValue);

                    i := i + 1;
                end;
            end;
        end;

        if PlacementsList.Count > 0 then
        begin
            Result := PlaceComponentsFromList(PlacementsList);
        end
        else
        begin
            Result := 'ERROR: No placements provided for place_components';
        end;
    finally
        PlacementsList.Free;
    end;
end;

// Extract the layout duplicator apply logic
function ExecuteLayoutDuplicatorApply(RequestData: TStringList): String;
var
    ParamValue: String;
    i: Integer;
    SourceList, DestList: TStringList;
begin
    // For this command, we need to extract the source and destination lists
    SourceList := TStringList.Create;
    DestList := TStringList.Create;
    
    try
        // Parse parameters from the request
        for i := 0 to RequestData.Count - 1 do
        begin
            // Look for source designators array
            if (Pos('"source_designators"', RequestData[i]) > 0) then
            begin
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')
                
                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    // Extract the designator value
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);
                    
                    if (ParamValue <> '') and (ParamValue <> '[') then
                        SourceList.Add(ParamValue);
                    
                    i := i + 1;
                end;
            end
            // Look for destination designators array
            else if (Pos('"destination_designators"', RequestData[i]) > 0) then
            begin
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')
                
                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    // Extract the designator value
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);
                    
                    if (ParamValue <> '') and (ParamValue <> '[') then
                        DestList.Add(ParamValue);
                    
                    i := i + 1;
                end;
            end
        end;
        
        if (SourceList.Count > 0) and (DestList.Count > 0) then
        begin
            Result := ApplyLayoutDuplicator(SourceList, DestList);
        end
        else
        begin
            Result := '{"success": false, "error": "Source or destination lists are empty"}';
        end;
    finally
        SourceList.Free;
        DestList.Free;
    end;
end;

// Function to execute get output job containers
function ExecuteGetOutputJobContainers(RequestData: TStringList): String;
var
    ParamValue: String;
    i: Integer;
    OutJobPath: String;
begin
    OutJobPath := '';
    
    // Parse parameters from the request
    for i := 0 to RequestData.Count - 1 do
    begin
        if (Pos('"outjob_path"', RequestData[i]) > 0) then
        begin
            // Found the outjob_path parameter
            ParamValue := Copy(RequestData[i], Pos(':', RequestData[i]) + 1, Length(RequestData[i]));
            ParamValue := TrimJSON(ParamValue);
            OutJobPath := ParamValue;
            break;
        end;
    end;
    
    // Call the appropriate function
    Result := GetOutputJobContainers(ROOT_DIR);
end;

// Function to execute run output jobs
function ExecuteRunOutputJobs(RequestData: TStringList): String;
var
    ParamValue: String;
    i: Integer;
    ContainersList: TStringList;
begin
    ContainersList := TStringList.Create;
    
    try
        // Parse parameters from the request
        for i := 0 to RequestData.Count - 1 do
        begin
            if (Pos('"container_names"', RequestData[i]) > 0) then
            begin
                // Parse the array in the next lines
                i := i + 1; // Move to the next line (should be '[')
                
                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    // Extract the container name
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);
                    
                    if (ParamValue <> '') and (ParamValue <> '[') then
                        ContainersList.Add(ParamValue);
                    
                    i := i + 1;
                end;
            end;
        end;
        
        if ContainersList.Count > 0 then
        begin
            Result := RunOutputJobs(ContainersList, ROOT_DIR);
        end
        else
        begin
            Result := '{"success": false, "error": "No container names specified"}';
        end;
    finally
        ContainersList.Free;
    end;
end;

// Extract the create PCB footprint logic
function ExecuteCreatePCBFootprint(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    FootprintName: String;
    Description: String;
    PadsList: TStringList;
    CourtyardXMM: Double;
    CourtyardYMM: Double;
begin
    FootprintName := '';
    Description := '';
    CourtyardXMM := 0;
    CourtyardYMM := 0;
    PadsList := TStringList.Create;

    try
        for i := 0 to RequestData.Count - 1 do
        begin
            if (Pos('"footprint_name"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                FootprintName := TrimJSON(Copy(RequestData[i], ValueStart, Length(RequestData[i])));
            end
            else if (Pos('"description"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                Description := TrimJSON(Copy(RequestData[i], ValueStart, Length(RequestData[i])));
            end
            else if (Pos('"courtyard_x_mm"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := TrimJSON(Copy(RequestData[i], ValueStart, Length(RequestData[i])));
                CourtyardXMM := SafeStrToFloat(ParamValue);
            end
            else if (Pos('"courtyard_y_mm"', RequestData[i]) > 0) then
            begin
                ValueStart := Pos(':', RequestData[i]) + 1;
                ParamValue := TrimJSON(Copy(RequestData[i], ValueStart, Length(RequestData[i])));
                CourtyardYMM := SafeStrToFloat(ParamValue);
            end
            else if (Pos('"pads"', RequestData[i]) > 0) then
            begin
                i := i + 1;
                while (i < RequestData.Count) and (Pos(']', RequestData[i]) = 0) do
                begin
                    ParamValue := RequestData[i];
                    ParamValue := StringReplace(ParamValue, '"', '', REPLACEALL);
                    ParamValue := StringReplace(ParamValue, ',', '', REPLACEALL);
                    ParamValue := Trim(ParamValue);
                    if (ParamValue <> '') and (ParamValue <> '[') then
                        PadsList.Add(ParamValue);
                    i := i + 1;
                end;
            end;
        end;

        if FootprintName <> '' then
            Result := CreatePCBFootprint(FootprintName, Description, PadsList, CourtyardXMM, CourtyardYMM)
        else
            Result := '{"success": false, "error": "No footprint name provided"}';
    finally
        PadsList.Free;
    end;
end;

// Extract the search library symbol logic
function ExecuteSearchLibrarySymbol(RequestData: TStringList): String;
var
    ParamValue: String;
    i, ValueStart: Integer;
    LibraryPath: String;
    SymbolName: String;
begin
    LibraryPath := '';
    SymbolName := '';

    // Parse parameters from the request
    for i := 0 to RequestData.Count - 1 do
    begin
        // Look for library_path
        if (Pos('"library_path"', RequestData[i]) > 0) then
        begin
            ValueStart := Pos(':', RequestData[i]) + 1;
            ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
            ParamValue := TrimJSON(ParamValue);
            LibraryPath := ParamValue;
        end
        // Look for symbol_name
        else if (Pos('"symbol_name"', RequestData[i]) > 0) then
        begin
            ValueStart := Pos(':', RequestData[i]) + 1;
            ParamValue := Copy(RequestData[i], ValueStart, Length(RequestData[i]) - ValueStart + 1);
            ParamValue := TrimJSON(ParamValue);
            SymbolName := ParamValue;
        end;
    end;

    if SymbolName <> '' then
    begin
        Result := SearchLibrarySymbol(ROOT_DIR, LibraryPath, SymbolName);
    end
    else
    begin
        Result := 'ERROR: No symbol name provided for search_library_symbol';
    end;
end;

// Function to execute a command with parameters
// Local pilot policy. These paths cannot be overridden by tool arguments.
// BEGIN GENERATED BRIDGE POLICY
// Generated from pilot_policy.json. Do not edit independently.
function BridgePolicyIdentity(Dummy: Integer): String;
begin Result := '2cc3ce78694e8cd56ec520551682efdcfe65d81947838ce9b9b7875b08ed4d2c'; end;
function BridgeTargetProjectPath(Dummy: Integer): String;
begin Result := 'c:\altiumprojects\example\example.prjpcb'; end;
function BridgeExpectedDocuments(Dummy: Integer): Integer;
begin Result := 16; end;
function BridgeExpectedSchematics(Dummy: Integer): Integer;
begin Result := 13; end;
function BridgeApprovedProject(FilePath: String): Boolean;
var P: String;
begin
  P := LowerCase(ExpandFileName(FilePath));
  Result := (P = 'c:\altiumprojects\example\example.prjpcb');
end;
function BridgeCurrentRoot(Dummy: Integer): String;
var Project: IProject; R: String;
begin
  Result := ''; Project := PilotReadProject(0); if Project = nil then Exit;
  if not BridgeApprovedProject(Project.DM_ProjectFullPath) then Exit;
  R := LowerCase(ExtractFilePath(ExpandFileName(Project.DM_ProjectFullPath)));
  if (Length(R) > 0) and (R[Length(R)] = '\') then Delete(R, Length(R), 1);
  Result := R;
end;
function BridgeExpectedBoard(Dummy: Integer): String;
begin Result := BridgeCurrentRoot(0) + '\board.pcbdoc'; end;
function BridgeAllowedDocument(FilePath: String): Boolean;
var P, R: String;
begin
  P := LowerCase(ExpandFileName(FilePath));
  R := BridgeCurrentRoot(0); if R = '' then begin Result := False; Exit; end;
  Result := (P = R + '\sheet01.schdoc') or
    (P = R + '\sheet02.schdoc') or
    (P = R + '\sheet03.schdoc') or
    (P = R + '\sheet04.schdoc') or
    (P = R + '\sheet05.schdoc') or
    (P = R + '\sheet06.schdoc') or
    (P = R + '\sheet07.schdoc') or
    (P = R + '\sheet08.schdoc') or
    (P = R + '\sheet09.schdoc') or
    (P = R + '\sheet10.schdoc') or
    (P = R + '\sheet11.schdoc') or
    (P = R + '\sheet12.schdoc') or
    (P = R + '\sheet13.schdoc') or
    (P = R + '\board.pcbdoc') or
    (P = R + '\board_previous.pcbdoc') or
    (P = R + '\example.bomdoc');
end;
function BridgeAllowedCommand(CommandName: String): Boolean;
begin Result := (CommandName = 'get_read_context') or
    (CommandName = 'get_all_component_data') or
    (CommandName = 'get_component_pins') or
    (CommandName = 'get_all_nets') or
    (CommandName = 'get_pcb_layers') or
    (CommandName = 'get_pcb_rules') or
    (CommandName = 'get_schematic_data') or
    (CommandName = 'bridge_snapshot') or
    (CommandName = 'bridge_messages') or
    (CommandName = 'bridge_measure') or
    (CommandName = 'bridge_apply') or
    (CommandName = 'bridge_restore') or
    (CommandName = 'bridge_analysis'); end;
// END GENERATED BRIDGE POLICY

function PilotAllowedCommand(CommandName: String): Boolean;
begin Result := BridgeAllowedCommand(CommandName); end;

function PilotAllowedDocument(FilePath: String): Boolean;
begin Result := BridgeAllowedDocument(FilePath); end;

function PilotVirtualDocument(FilePath, Kind: String): Boolean;
begin
    Result := (Kind = 'VirtualBOM') and
        (LowerCase(ExpandFileName(FilePath)) = BridgeCurrentRoot(0) + '\activebom.virtualbom') and
        (not FileExists(FilePath));
end;

function PilotValidRequestId(Value: String): Boolean;
var I: Integer;
begin
    Result := False;
    if Length(Value) <> 32 then Exit;
    for I := 1 to Length(Value) do
        if Pos(Value[I], '0123456789abcdef') = 0 then Exit;
    Result := True;
end;

function PilotValidateScope(RequireBoard: Boolean): String;
var
    Project: IProject;
    Doc: IDocument;
    Board: IPCB_Board;
    I, SchCount, VirtualCount: Integer;
    Seen: TStringList;
    P, Suffix: String;
begin
    Result := '';
    Project := PilotReadProject(0);
    if Project = nil then begin Result := 'TARGET_PROJECT_NOT_OPEN'; Exit; end;
    if not BridgeApprovedProject(Project.DM_ProjectFullPath) then
    begin
        Result := 'PROJECT_SCOPE_MISMATCH actual_project=' + Project.DM_ProjectFullPath;
        Doc := GetWorkspace.DM_FocusedDocument;
        if Doc <> nil then Result := Result + ' focused_document=' + Doc.DM_FullPath;
        Board := GetBoardSafe(0);
        if Board <> nil then Result := Result + ' pcb_board_path=' + Board.FileName;
        Exit;
    end;
    // The manifest target, member inventory and PCB path establish scope.
    SchCount := 0;
    VirtualCount := 0;
    Seen := TStringList.Create;
    try
        for I := 0 to Project.DM_LogicalDocumentCount - 1 do
        begin
            Doc := Project.DM_LogicalDocuments(I);
            P := LowerCase(ExpandFileName(Doc.DM_FullPath));
            if PilotVirtualDocument(Doc.DM_FullPath, Doc.DM_DocumentKind) then
                VirtualCount := VirtualCount + 1
            else
            begin
                if (not PilotAllowedDocument(Doc.DM_FullPath)) or
                   (Seen.IndexOf(P) >= 0) then
                    begin Result := 'DOCUMENT_SCOPE_MISMATCH unexpected_or_duplicate=' + Doc.DM_FullPath; Exit; end;
                Seen.Add(P);
                Suffix := Copy(P, Length(P) - 6, 7);
                if ((Suffix = '.schdoc') and (Doc.DM_DocumentKind <> 'SCH')) or
                   ((Suffix = '.pcbdoc') and (Doc.DM_DocumentKind <> 'PCB')) then
                    begin Result := 'DOCUMENT_KIND_MISMATCH'; Exit; end;
                if Doc.DM_DocumentKind = 'SCH' then SchCount := SchCount + 1;
            end;
        end;
        if (Seen.Count <> BridgeExpectedDocuments(0)) or (VirtualCount > 1) then
            begin Result := 'DOCUMENT_INVENTORY_MISMATCH'; Exit; end;
    finally
        Seen.Free;
    end;
    if SchCount <> BridgeExpectedSchematics(0) then begin Result := 'SCHEMATIC_INVENTORY_MISMATCH'; Exit; end;
    if not RequireBoard then Exit;
    Board := GetBoardSafe(1);
    if Board = nil then
    begin
        if RequireBoard then Result := 'TARGET_PCB_NOT_LOADED';
        Exit;
    end;
    if LowerCase(ExpandFileName(Board.FileName)) <> BridgeExpectedBoard(0) then
        Result := 'BOARD_SCOPE_MISMATCH';
end;

function PilotBuildContext(): String;
var
    Project, FocusedProject: IProject;
    Doc: IDocument;
    Board: IPCB_Board;
    Props, Documents, VirtualDocuments, DocProps: TStringList;
    I: Integer;
begin
    Project := PilotReadProject(0);
    Props := TStringList.Create;
    Documents := TStringList.Create;
    VirtualDocuments := TStringList.Create;
    try
        Doc := GetWorkspace.DM_FocusedDocument;
        FocusedProject := GetWorkspace.DM_FocusedProject;
        AddJSONProperty(Props, 'project_path', Project.DM_ProjectFullPath);
        AddJSONProperty(Props, 'project_identity_source', 'manifest_target_path');
        if Doc <> nil then AddJSONProperty(Props, 'focused_document_path', Doc.DM_FullPath)
        else AddJSONProperty(Props, 'focused_document_path', 'null', False);
        if FocusedProject <> nil then
            AddJSONProperty(Props, 'workspace_focused_project_path', FocusedProject.DM_ProjectFullPath)
        else
            AddJSONProperty(Props, 'workspace_focused_project_path', 'null', False);
        AddJSONBoolean(Props, 'scope_verified', True);
        AddJSONBoolean(Props, 'read_complete', True);
        AddJSONProperty(Props, 'dirty_state', BridgeProjectDirtyState(0));
        for I := 0 to Project.DM_LogicalDocumentCount - 1 do
        begin
            Doc := Project.DM_LogicalDocuments(I);
            DocProps := TStringList.Create;
            try
                AddJSONProperty(DocProps, 'path', Doc.DM_FullPath);
                AddJSONProperty(DocProps, 'kind', Doc.DM_DocumentKind);
                if PilotVirtualDocument(Doc.DM_FullPath, Doc.DM_DocumentKind) then
                    VirtualDocuments.Add(BuildJSONObject(DocProps))
                else
                    Documents.Add(BuildJSONObject(DocProps));
            finally
                DocProps.Free;
            end;
        end;
        Props.Add(JSONPairStr('documents', BuildJSONArray(Documents), False));
        Props.Add(JSONPairStr('virtual_documents', BuildJSONArray(VirtualDocuments), False));
        Board := GetBoardSafe(0);
        if Board <> nil then
            if LowerCase(ExpandFileName(Board.FileName)) <> BridgeExpectedBoard(0) then Board := nil;
        if Board <> nil then
        begin
            AddJSONProperty(Props, 'board_path', Board.FileName);
            AddJSONProperty(Props, 'pcb_coordinate_units', 'mil');
            AddJSONProperty(Props, 'pcb_coordinate_reference', 'component position minus board origin');
            AddJSONNumber(Props, 'pcb_origin_x_mil', CoordToMils(Board.XOrigin));
            AddJSONNumber(Props, 'pcb_origin_y_mil', CoordToMils(Board.YOrigin));
            AddJSONProperty(Props, 'pcb_display_units', UnitToString(Board.DisplayUnit));
        end
        else AddJSONProperty(Props, 'board_path', 'NOT_VERIFIED');
        Result := BuildJSONObject(Props);
    finally
        VirtualDocuments.Free;
        Documents.Free;
        Props.Free;
    end;
end;

function ExecuteCommand(CommandName: String): String;
var
    ScopeError : String;
    ViewHint   : String;
    HintIdx    : Integer;
    HintStart  : Integer;
    HintValue  : String;
begin
    Result := '';

    // take_view_screenshot can target a PCB or a schematic. Pull view_type out
    // of the request so the focus helper does not always demand a PCB.
    ViewHint := '';
    if CommandName = 'take_view_screenshot' then
    begin
        for HintIdx := 0 to RequestData.Count - 1 do
        begin
            if (Pos('"view_type"', RequestData[HintIdx]) > 0) then
            begin
                HintStart := Pos(':', RequestData[HintIdx]) + 1;
                HintValue := Copy(RequestData[HintIdx], HintStart,
                                  Length(RequestData[HintIdx]) - HintStart + 1);
                ViewHint := LowerCase(TrimJSON(HintValue));
            end;
        end;
    end;

    // Reject commands and scope before any opening, focusing or data read.
    if not PilotAllowedCommand(CommandName) then
    begin Result := 'ERROR: COMMAND_NOT_ALLOWED'; Exit; end;
    PilotTrace('scope_check_started');
    ScopeError := PilotValidateScope((CommandName <> 'get_schematic_data') and
        (CommandName <> 'get_read_context') and (CommandName <> 'bridge_messages'));
    if ScopeError <> '' then begin Result := 'ERROR: ' + ScopeError; Exit; end;
    PilotTrace('scope_check_passed');
    PilotContext := PilotBuildContext();
    PilotTrace('context_built');
    if CommandName = 'get_read_context' then begin Result := PilotContext; Exit; end;
    if CommandName = 'bridge_messages' then begin Result := BridgeReadMessages(Params); Exit; end;
    if CommandName = 'bridge_snapshot' then begin Result := BridgeReadSnapshot(Params); Exit; end;
    if CommandName = 'bridge_measure' then begin Result := BridgeMeasure(Params); Exit; end;
    if (CommandName = 'bridge_apply') or (CommandName = 'bridge_restore') then
        begin Result := BridgeControlledChange(CommandName, Params); Exit; end;
    if CommandName = 'bridge_analysis' then
        begin Result := 'ERROR: ANALYSIS_JOB_NATIVE_ACCEPTANCE_REQUIRED'; Exit; end;


    // Direct command execution based on the command name
    case CommandName of
        'get_component_pins':
            Result := ExecuteGetComponentPins(RequestData);            
        'get_all_nets':
            Result := GetAllNets(ROOT_DIR);            
        'create_net_class':
            Result := ExecuteCreateNetClass(RequestData);            
        'get_all_component_data':
            Result := GetAllComponentData(ROOT_DIR, False);            
        'take_view_screenshot':
            Result := ExecuteTakeViewScreenshot(RequestData);            
        'get_library_symbol_reference':
            Result := GetLibrarySymbolReference(ROOT_DIR);            
        'create_schematic_symbol':
            Result := ExecuteCreateSchematicSymbol(RequestData);            
        'get_schematic_data':
            Result := GetSchematicData(ROOT_DIR);            
        'get_pcb_layers':
            Result := GetPCBLayers(ROOT_DIR);            
        'set_pcb_layer_visibility':
            Result := ExecuteSetPCBLayerVisibility(RequestData);   
        'get_pcb_layer_stackup':
            Result := GetPCBLayerStackup(ROOT_DIR);         
        'get_selected_components_coordinates':
            Result := GetSelectedComponentsCoordinates(ROOT_DIR); 
		'set_component_position':
			Result := ExecuteSetComponentPosition(RequestData);
        'move_components':
            Result := ExecuteMoveComponents(RequestData);
        'place_components':
            Result := ExecutePlaceComponents(RequestData);
        'check_placement':
            Result := ExecuteCheckPlacement(RequestData);
        'get_net_connections':
            Result := ExecuteGetNetConnections(RequestData);
        'get_symbol_primitives':
            Result := ExecuteGetSymbolPrimitives(RequestData);
        'create_symbols_batch':
            Result := ExecuteCreateSymbolsBatch(RequestData);
        'build_circuit':
            Result := BuildCircuitFromSpec(ROOT_DIR + 'circuit_spec.txt',
                                          ROOT_DIR + 'param_placement.txt');
        'get_footprint_primitives':
            Result := ExecuteGetFootprintPrimitives(RequestData);
        'create_footprints_batch':
            Result := ExecuteCreateFootprintsBatch(RequestData);
        'layout_duplicator':
            Result := GetLayoutDuplicatorComponents(True);            
        'layout_duplicator_apply':
            Result := ExecuteLayoutDuplicatorApply(RequestData);            
        'get_pcb_rules':
            Result := GetPCBRules(ROOT_DIR);
        'get_output_job_containers':
            Result := ExecuteGetOutputJobContainers(RequestData);
        'run_output_jobs':
            Result := ExecuteRunOutputJobs(RequestData);
        'search_library_symbol':
            Result := ExecuteSearchLibrarySymbol(RequestData);
        'create_pcb_footprint':
            Result := ExecuteCreatePCBFootprint(RequestData);
    else
        Result := 'ERROR: COMMAND_NOT_ALLOWED';
    end;
end;

// Function to extract a parameter name-value pair from a JSON line
procedure ExtractParameter(Line: String);
var
    ParamName: String;
    ParamValue: String;
    NameEnd: Integer;
    ValueStart: Integer;
begin
    // Skip command line and lines without a colon
    if (Pos('"command":', Line) > 0) or (Pos(':', Line) = 0) then
        Exit;

    // Find the parameter name
    NameEnd := Pos(':', Line) - 1;
    if NameEnd <= 0 then Exit;

    // Extract and clean the parameter name
    ParamName := Copy(Line, 1, NameEnd);
    ParamName := TrimJSON(ParamName);

    // Extract the parameter value - don't trim arrays
    ValueStart := Pos(':', Line) + 1;
    ParamValue := Copy(Line, ValueStart, Length(Line) - ValueStart + 1);

    // Trim only if it's not an array
    if (Pos('[', ParamValue) = 0) then
        ParamValue := TrimJSON(ParamValue);

    // Add to parameters list
    if (ParamName <> '') and (ParamName <> 'command') then
        Params.Add(ParamName + '=' + ParamValue);
end;

procedure WriteResponse(Success: Boolean; Data: String; ErrorMsg: String);
var
    ActualSuccess: Boolean;
    ActualErrorMsg: String;
    ResultProps: TStringList;
begin
    // Check if Data contains an error message
    if (Pos('ERROR:', Data) = 1) then
    begin
        ActualSuccess := False;
        ActualErrorMsg := Copy(Data, 8, Length(Data)); // Remove 'ERROR: ' prefix
    end
    else
    begin
        ActualSuccess := Success;
        ActualErrorMsg := ErrorMsg;
    end;

    // Create response props
    ResultProps := TStringList.Create;
    ResponseData := TStringList.Create;
    
    try
        // Add properties
        AddJSONProperty(ResultProps, 'request_id', PilotRequestId);
        AddJSONProperty(ResultProps, 'policy_id', BridgePolicyIdentity(0));
        AddJSONBoolean(ResultProps, 'success', ActualSuccess);
        if ActualSuccess then ResultProps.Add(JSONPairStr('context', PilotContext, False));
        
        if ActualSuccess then
        begin
            // For JSON responses (starting with [ or {), don't wrap in additional quotes
            if (Length(Data) > 0) and ((Data[1] = '[') or (Data[1] = '{')) then
                ResultProps.Add(JSONPairStr('result', Data, False))
            else
                AddJSONProperty(ResultProps, 'result', Data);
        end
        else
        begin
            AddJSONProperty(ResultProps, 'error', ActualErrorMsg);
        end;
        
        // Build response
        ResponseData.Text := BuildJSONObject(ResultProps);
        ResponseData.SaveToFile(RESPONSE_FILE + '.tmp');
        PilotTrace('response_temporary_written');
        if not RenameFile(RESPONSE_FILE + '.tmp', RESPONSE_FILE) then
            Raise('ATOMIC_RESPONSE_PUBLICATION_FAILED');
        PilotTrace('response_published');
    finally
        ResultProps.Free;
        ResponseData.Free;
    end;
end;

// Main procedure to run the bridge
procedure Run;
var
    CommandType: String;
    Result: String;
    i: Integer;
    Line: String;
    ValueStart: Integer;
begin
    // Initialize file paths based on script location
    InitializeFilePaths();
    PilotRequestId := '';
    PilotContext := '{}';
    PilotTrace('run_entered');

    // Check if request file exists
    if not FileExists(REQUEST_FILE) then
    begin
        Exit;
    end;

    try
        // Initialize parameters list
        Params := TStringList.Create;
        Params.Delimiter := '=';

        // Read the request file
        RequestData := TStringList.Create;
        try
            RequestData.LoadFromFile(REQUEST_FILE);
            PilotTrace('request_loaded');

            // Default command type
            CommandType := '';

            // Parse command and parameters
            for i := 0 to RequestData.Count - 1 do
            begin
                Line := RequestData[i];

                // Extract command
                if Pos('"command":', Line) > 0 then
                begin
                    ValueStart := Pos(':', Line) + 1;
                    CommandType := Copy(Line, ValueStart, Length(Line) - ValueStart + 1);
                    CommandType := TrimJSON(CommandType);
                end
                else
                begin
                    // Extract all other parameters
                    ExtractParameter(Line);
                end;
            end;

            PilotRequestId := Params.Values['request_id'];
            PilotTrace('request_id_read');
            if not PilotValidRequestId(PilotRequestId) then Exit;
            RESPONSE_FILE := ROOT_DIR + 'response-' + PilotRequestId + '.json';
            if Params.Values['policy_id'] <> BridgePolicyIdentity(0) then
            begin WriteResponse(False, '', 'REQUEST_POLICY_MISMATCH'); Exit; end;
            PilotTrace('policy_verified');

            // Execute the command if valid
            if CommandType <> '' then
            begin
                Result := ExecuteCommand(CommandType);

                if Result <> '' then
                begin
                    WriteResponse(True, Result, '');
                end
                else
                begin
                    WriteResponse(False, '', 'Command execution failed');
                end;
            end
            else
            begin
                WriteResponse(False, '', 'No command specified');
            end;
        finally
            RequestData.Free;
            Params.Free;
        end;
    except
        // Simple exception handling without the specific exception type
        WriteResponse(False, '', 'Exception occurred during script execution');
    end;
end;


