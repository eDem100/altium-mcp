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
