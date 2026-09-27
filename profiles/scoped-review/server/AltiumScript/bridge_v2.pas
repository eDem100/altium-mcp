// V2 native collection. No reader runs compile, DRC, repour or save.

function BridgeProjectDirtyState(Dummy: Integer): String;
var Project: IProject; Doc: IDocument; ServerDoc: IServerDocument; I: Integer;
begin
    Result := 'clean'; Project := PilotReadProject(0);
    if Project = nil then begin Result := 'unknown'; Exit; end;
    try
        for I := 0 to Project.DM_LogicalDocumentCount - 1 do
        begin
            Doc := Project.DM_LogicalDocuments(I);
            ServerDoc := Client.GetDocumentByPath(Doc.DM_FullPath);
            if ServerDoc <> nil then
                if ServerDoc.Modified then begin Result := 'dirty'; Exit; end;
        end;
    except Result := 'unknown'; end;
end;

procedure BridgeMissing(P: TStringList; Field, Reason: String);
begin
    AddJSONProperty(P, Field, 'null', False);
    AddJSONProperty(P, Field + '_unavailable_reason', Reason);
end;

function BridgePCBObject(Prim: IPCB_Primitive; Board: IPCB_Board): String;
var P, Layers, LP, Points, PP: TStringList; Rect: TCoordRect;
    LI: IPCB_LayerObjectIterator; L: TLayer; I: Integer;
begin
    P := TStringList.Create;
    try
        AddJSONProperty(P, 'address_session', IntToStr(Prim.I_ObjectAddress));
        AddJSONInteger(P, 'object_kind_id', Prim.ObjectId);
        AddJSONProperty(P, 'descriptor', Prim.ObjectIDString);
        AddJSONProperty(P, 'layer', Layer2String(Prim.Layer));
        try
            if Prim.Net <> nil then AddJSONProperty(P, 'net', Prim.Net.Name)
            else AddJSONProperty(P, 'net', '');
        except BridgeMissing(P, 'net', 'Native net unavailable'); end;
        try
            if Prim.Component <> nil then AddJSONProperty(P, 'component', Prim.Component.Name.Text)
            else AddJSONProperty(P, 'component', '');
        except BridgeMissing(P, 'component', 'Native owner unavailable'); end;
        try AddJSONBoolean(P, 'moveable', Prim.Moveable);
        except BridgeMissing(P, 'moveable', 'Lock state unavailable'); end;
        Rect := Prim.BoundingRectangle;
        AddJSONInteger(P, 'bounds_left_coord', Rect.Left); AddJSONInteger(P, 'bounds_bottom_coord', Rect.Bottom);
        AddJSONInteger(P, 'bounds_right_coord', Rect.Right); AddJSONInteger(P, 'bounds_top_coord', Rect.Top);
        try
            AddJSONBoolean(P, 'keepout', Prim.IsKeepout);
            case Prim.ObjectId of
                eComponentObject:
                begin
                    AddJSONProperty(P, 'kind', 'component'); AddJSONProperty(P, 'designator', Prim.Name.Text);
                    AddJSONProperty(P, 'footprint', Prim.Pattern);
                    AddJSONInteger(P, 'x_coord', Prim.x); AddJSONInteger(P, 'y_coord', Prim.y);
                    AddJSONNumber(P, 'rotation_deg', Prim.Rotation);
                    BridgeMissing(P, 'courtyard', 'Mechanical roles not verified; bounds are not courtyard');
                end;
                eTrackObject:
                begin
                    AddJSONProperty(P, 'kind', 'track');
                    AddJSONInteger(P, 'x1_coord', Prim.x1); AddJSONInteger(P, 'y1_coord', Prim.y1);
                    AddJSONInteger(P, 'x2_coord', Prim.x2); AddJSONInteger(P, 'y2_coord', Prim.y2);
                    AddJSONInteger(P, 'width_coord', Prim.Width);
                end;
                eArcObject:
                begin
                    AddJSONProperty(P, 'kind', 'arc');
                    AddJSONInteger(P, 'x_coord', Prim.XCenter); AddJSONInteger(P, 'y_coord', Prim.YCenter);
                    AddJSONInteger(P, 'radius_coord', Prim.Radius); AddJSONInteger(P, 'width_coord', Prim.LineWidth);
                    AddJSONNumber(P, 'start_angle_deg', Prim.StartAngle); AddJSONNumber(P, 'end_angle_deg', Prim.EndAngle);
                end;
                ePadObject:
                begin
                    AddJSONProperty(P, 'kind', 'pad'); AddJSONProperty(P, 'pin', Prim.Name);
                    AddJSONInteger(P, 'x_coord', Prim.x); AddJSONInteger(P, 'y_coord', Prim.y);
                    AddJSONNumber(P, 'rotation_deg', Prim.Rotation);
                    AddJSONInteger(P, 'hole_coord', Prim.HoleSize); AddJSONBoolean(P, 'plated', Prim.Plated);
                    AddJSONInteger(P, 'hole_type', Prim.HoleType); AddJSONInteger(P, 'hole_width_coord', Prim.HoleWidth);
                    Layers := TStringList.Create; LI := Board.ElectricalLayerIterator;
                    try
                        while LI.Next do
                        begin
                            L := LI.LayerObject.LayerID; LP := TStringList.Create;
                            try
                                AddJSONProperty(LP, 'layer', Layer2String(L));
                                AddJSONInteger(LP, 'x_size_coord', Prim.XSizeOnLayer[L]);
                                AddJSONInteger(LP, 'y_size_coord', Prim.YSizeOnLayer[L]);
                                AddJSONInteger(LP, 'shape', Prim.ShapeOnLayer[L]);
                                Layers.Add(BuildJSONObject(LP));
                            finally LP.Free; end;
                        end;
                        P.Add(JSONPairStr('pad_layers', BuildJSONArray(Layers), False));
                    finally Layers.Free; end;
                    BridgeMissing(P, 'unused_pad_removal', 'Suppression flags not yet verified');
                    try AddJSONInteger(P, 'solder_mask_expansion_coord', Prim.SolderMaskExpansion);
                    except BridgeMissing(P, 'solder_mask_expansion_coord', 'Getter unavailable'); end;
                    try AddJSONInteger(P, 'paste_mask_expansion_coord', Prim.PasteMaskExpansion);
                    except BridgeMissing(P, 'paste_mask_expansion_coord', 'Getter unavailable'); end;
                end;
                eViaObject:
                begin
                    AddJSONProperty(P, 'kind', 'via');
                    AddJSONInteger(P, 'x_coord', Prim.x); AddJSONInteger(P, 'y_coord', Prim.y);
                    AddJSONInteger(P, 'size_coord', Prim.Size); AddJSONInteger(P, 'hole_coord', Prim.HoleSize);
                    AddJSONProperty(P, 'low_layer', Layer2String(Prim.LowLayer)); AddJSONProperty(P, 'high_layer', Layer2String(Prim.HighLayer));
                    BridgeMissing(P, 'via_stack', 'Per-layer suppression not yet verified');
                end;
                eTextObject:
                begin
                    AddJSONProperty(P, 'kind', 'text'); AddJSONProperty(P, 'text', Prim.Text);
                    AddJSONInteger(P, 'x_coord', Prim.XLocation); AddJSONInteger(P, 'y_coord', Prim.YLocation);
                    AddJSONInteger(P, 'size_coord', Prim.Size); AddJSONInteger(P, 'width_coord', Prim.Width);
                    AddJSONNumber(P, 'rotation_deg', Prim.Rotation); AddJSONBoolean(P, 'mirror', Prim.MirrorFlag);
                end;
                eFillObject:
                begin
                    AddJSONProperty(P, 'kind', 'fill');
                    AddJSONInteger(P, 'x1_coord', Prim.x1Location); AddJSONInteger(P, 'y1_coord', Prim.y1Location);
                    AddJSONInteger(P, 'x2_coord', Prim.x2Location); AddJSONInteger(P, 'y2_coord', Prim.y2Location);
                    AddJSONNumber(P, 'rotation_deg', Prim.Rotation);
                end;
                eRegionObject:
                begin
                    AddJSONProperty(P, 'kind', 'region'); AddJSONInteger(P, 'region_kind', Prim.Kind);
                    Points := TStringList.Create;
                    try
                        for I := 1 to Prim.MainContour.Count do
                        begin
                            PP := TStringList.Create;
                            try
                                AddJSONInteger(PP, 'x_coord', Prim.MainContour.x[I]); AddJSONInteger(PP, 'y_coord', Prim.MainContour.y[I]);
                                Points.Add(BuildJSONObject(PP));
                            finally PP.Free; end;
                        end;
                        P.Add(JSONPairStr('contour', BuildJSONArray(Points), False));
                        AddJSONInteger(P, 'hole_count', Prim.HoleCount);
                        if Prim.HoleCount > 0 then BridgeMissing(P, 'holes', 'Hole contours not yet decoded');
                    finally Points.Free; end;
                end;
                ePolyObject:
                begin
                    AddJSONProperty(P, 'kind', 'polygon');
                    BridgeMissing(P, 'outline_and_pour_state', 'Boundary and poured copper require validation');
                end;
                eRuleObject:
                begin
                    AddJSONProperty(P, 'kind', 'rule'); AddJSONProperty(P, 'name', Prim.Name);
                    AddJSONProperty(P, 'unique_id', Prim.UniqueId); AddJSONProperty(P, 'rule_kind', Prim.GetState_ShortDescriptorString);
                    AddJSONProperty(P, 'scope1', Prim.Scope1Expression); AddJSONProperty(P, 'scope2', Prim.Scope2Expression);
                    AddJSONBoolean(P, 'enabled', Prim.DRCEnabled); AddJSONInteger(P, 'priority', Prim.Priority);
                    AddJSONProperty(P, 'native_summary', Prim.GetState_DataSummaryString);
                    AddJSONInteger(P, 'rule_kind_id', Prim.RuleKind);
                    case Prim.RuleKind of
                        eRule_Clearance: AddJSONInteger(P, 'gap_coord', Prim.Gap);
                        eRule_MaxMinLength:
                        begin AddJSONInteger(P, 'min_length_coord', Prim.MinLimit); AddJSONInteger(P, 'max_length_coord', Prim.MaxLimit); end;
                        eRule_MatchedLengths: AddJSONInteger(P, 'tolerance_coord', Prim.Tolerance);
                        eRule_MaxMinWidth:
                        begin
                            Layers := TStringList.Create; LI := Board.ElectricalLayerIterator;
                            try
                                while LI.Next do
                                begin
                                    L := LI.LayerObject.LayerID; LP := TStringList.Create;
                                    try
                                        AddJSONProperty(LP, 'layer', Layer2String(L));
                                        AddJSONInteger(LP, 'min_width_coord', Prim.MinWidth[L]);
                                        AddJSONInteger(LP, 'preferred_width_coord', Prim.FavoredWidth[L]);
                                        AddJSONInteger(LP, 'max_width_coord', Prim.MaxWidth[L]);
                                        Layers.Add(BuildJSONObject(LP));
                                    finally LP.Free; end;
                                end;
                                P.Add(JSONPairStr('width_by_layer', BuildJSONArray(Layers), False));
                            finally Layers.Free; end;
                        end;
                    else BridgeMissing(P, 'typed_constraints', 'This rule-specific native interface has not been validated');
                    end;
                    BridgeMissing(P, 'effective_for_objects', 'Resolve applicability for requested objects');
                end;
            else
                begin
                    AddJSONProperty(P, 'kind', 'other'); BridgeMissing(P, 'specific_geometry', 'Inventoried type not yet decoded');
                end;
            end;
        except
            AddJSONProperty(P, 'field_read_status', 'partial'); AddJSONProperty(P, 'field_read_error', 'Native getter failed');
        end;
        Result := BuildJSONObject(P);
    finally P.Free; end;
end;

function BridgeBoardObjects(Offset, Limit: Integer; Kind, ComponentName: String; var Total: Integer): String;
var Board: IPCB_Board; It: IPCB_BoardIterator; Prim: IPCB_Primitive; Records: TStringList;
    Count: Integer; Include: Boolean;
begin
    PilotTrace('snapshot_pcb_iterator_begin');
    Board := GetBoardSafe(0);
    if Board = nil then begin Result := 'ERROR: NO_ACTIVE_PILOT_BOARD'; Exit; end;
    Records := TStringList.Create; It := Board.BoardIterator_Create;
    try
        if Kind = 'all' then It.AddFilter_ObjectSet(AllObjects)
        else if Kind = 'component' then It.AddFilter_ObjectSet(MkSet(eComponentObject))
        else if Kind = 'rule' then It.AddFilter_ObjectSet(MkSet(eRuleObject))
        else if Kind = 'pad' then It.AddFilter_ObjectSet(MkSet(ePadObject))
        else if Kind = 'via' then It.AddFilter_ObjectSet(MkSet(eViaObject))
        else if Kind = 'track' then It.AddFilter_ObjectSet(MkSet(eTrackObject))
        else if Kind = 'arc' then It.AddFilter_ObjectSet(MkSet(eArcObject))
        else if Kind = 'text' then It.AddFilter_ObjectSet(MkSet(eTextObject))
        else if Kind = 'fill' then It.AddFilter_ObjectSet(MkSet(eFillObject))
        else if Kind = 'polygon' then It.AddFilter_ObjectSet(MkSet(ePolyObject))
        else if Kind = 'region' then It.AddFilter_ObjectSet(MkSet(eRegionObject))
        else begin Result := 'ERROR: INVALID_KIND_FILTER'; Exit; end;
        It.AddFilter_LayerSet(AllLayers); It.AddFilter_Method(eProcessAll);
        Prim := It.FirstPCBObject; Count := 0;
        while Prim <> nil do
        begin
            Include := ComponentName = '';
            if ComponentName <> '' then
            begin
                if Prim.ObjectId = eComponentObject then Include := Prim.Name.Text = ComponentName
                else if Prim.Component <> nil then Include := Prim.Component.Name.Text = ComponentName;
            end;
            if Include then
            begin
                if (Count >= Offset) and (Count < Offset + Limit) then
                    Records.Add(BridgePCBObject(Prim, Board));
                Count := Count + 1;
            end;
            Prim := It.NextPCBObject;
        end;
        Total := Count;
        if Offset > Total then begin Result := 'ERROR: PAGE_OFFSET_OUT_OF_RANGE'; Exit; end;
        PilotTrace('snapshot_pcb_page_complete_count_' + IntToStr(Records.Count));
        Result := BuildJSONArray(Records);
    finally Board.BoardIterator_Destroy(It); Records.Free; end;
end;

function BridgeSchematicObjects(Offset, Limit: Integer; var Total: Integer): String;
var Project: IProject; Doc: IDocument; Sch: ISch_Document; It: ISch_Iterator;
    Obj: ISch_BasicContainer; Comp: ISch_Component; Pin: ISch_Pin;
    Parameter: ISch_Parameter; LabelObj: ISch_Label; Port: ISch_Port;
    P, Records: TStringList; I, Count: Integer;
begin
    Project := PilotReadProject(0); Records := TStringList.Create; Count := 0;
    try
        for I := 0 to Project.DM_LogicalDocumentCount - 1 do
        begin
            Doc := Project.DM_LogicalDocuments(I);
            if Doc.DM_DocumentKind = 'SCH' then
            begin
                Sch := SchServer.GetSchDocumentByPath(Doc.DM_FullPath);
                if Sch = nil then
                begin
                    if (Count >= Offset) and (Count < Offset + Limit) then
                    begin
                    P := TStringList.Create;
                    try
                        AddJSONProperty(P, 'sheet', Doc.DM_FullPath); AddJSONProperty(P, 'status', 'unavailable');
                        AddJSONProperty(P, 'reason', 'Sheet not loaded; no implicit open or compile');
                        Records.Add(BuildJSONObject(P));
                    finally P.Free; end;
                    end;
                    Count := Count + 1;
                end
                else
                begin
                    It := Sch.SchIterator_Create;
                    try
                        It.SetState_IterationDepth(eIterateAllLevels); Obj := It.FirstSchObject;
                        while Obj <> nil do
                        begin
                            if (Count >= Offset) and (Count < Offset + Limit) then
                            begin
                            P := TStringList.Create;
                            try
                                AddJSONProperty(P, 'sheet', Doc.DM_FullPath); AddJSONInteger(P, 'object_kind_id', Obj.ObjectId);
                                try
                                    AddJSONProperty(P, 'unique_id', Obj.UniqueId);
                                    case Obj.ObjectId of
                                        eSchComponent:
                                        begin
                                            Comp := Obj;
                                            AddJSONProperty(P, 'kind', 'component'); AddJSONProperty(P, 'designator', Comp.Designator.Text);
                                            AddJSONProperty(P, 'library_reference', Comp.LibReference); AddJSONInteger(P, 'part_id', Comp.CurrentPartId);
                                        end;
                                        ePin:
                                        begin
                                            Pin := Obj;
                                            AddJSONProperty(P, 'kind', 'pin'); AddJSONProperty(P, 'pin', Pin.Designator);
                                            AddJSONProperty(P, 'name', Pin.Name); AddJSONInteger(P, 'electrical_type', Pin.Electrical);
                                            AddJSONInteger(P, 'x_coord', Pin.Location.X); AddJSONInteger(P, 'y_coord', Pin.Location.Y);
                                            AddJSONInteger(P, 'length_coord', Pin.PinLength); AddJSONInteger(P, 'orientation', Pin.Orientation);
                                        end;
                                        eParameter:
                                        begin
                                            Parameter := Obj;
                                            AddJSONProperty(P, 'kind', 'parameter'); AddJSONProperty(P, 'name', Parameter.Name); AddJSONProperty(P, 'text', Parameter.Text);
                                        end;
                                        eNetLabel, ePowerObject:
                                        begin
                                            LabelObj := Obj;
                                            AddJSONProperty(P, 'kind', 'net_or_port'); AddJSONProperty(P, 'text', LabelObj.Text);
                                        end;
                                        ePort:
                                        begin
                                            Port := Obj;
                                            AddJSONProperty(P, 'kind', 'net_or_port'); AddJSONProperty(P, 'text', Port.Name);
                                        end;
                                    else
                                        begin AddJSONProperty(P, 'kind', 'other'); BridgeMissing(P, 'specific_geometry', 'Object geometry not yet decoded'); end;
                                    end;
                                except AddJSONProperty(P, 'status', 'partial'); AddJSONProperty(P, 'reason', 'Native schematic getter unavailable'); end;
                                Records.Add(BuildJSONObject(P));
                            finally P.Free; end;
                            end;
                            Count := Count + 1;
                            Obj := It.NextSchObject;
                        end;
                    finally Sch.SchIterator_Destroy(It); end;
                end;
            end;
        end;
        Total := Count;
        if Offset > Total then begin Result := 'ERROR: PAGE_OFFSET_OUT_OF_RANGE'; Exit; end;
        Result := BuildJSONArray(Records);
    finally Records.Free; end;
end;

function BridgeReadSnapshot(Params: TStringList): String;
var P, Query: TStringList; BeforeObjects, AfterObjects, Dataset, Kind, ComponentName: String;
    Board: IPCB_Board; Offset, Limit, TotalBefore, TotalAfter: Integer;
begin
    PilotTrace('snapshot_begin');
    Dataset := Params.Values['dataset']; Offset := StrToInt(Params.Values['offset']);
    Limit := StrToInt(Params.Values['limit']);
    Kind := Params.Values['kind']; ComponentName := Params.Values['component'];
    if ((Dataset <> 'pcb') and (Dataset <> 'schematic')) or
       (Offset < 0) or (Offset > 1000000) or (Limit < 1) or (Limit > 100) then
    begin Result := 'ERROR: INVALID_SNAPSHOT_QUERY'; Exit; end;
    if (Dataset = 'schematic') and ((Kind <> 'all') or (ComponentName <> '')) then
    begin Result := 'ERROR: SCHEMATIC_FILTER_NOT_IMPLEMENTED'; Exit; end;
    P := TStringList.Create;
    try
        Board := GetBoardSafe(0);
        if Dataset = 'pcb' then BeforeObjects := BridgeBoardObjects(Offset, Limit, Kind, ComponentName, TotalBefore)
        else BeforeObjects := BridgeSchematicObjects(Offset, Limit, TotalBefore);
        if Pos('ERROR:', BeforeObjects) = 1 then begin Result := BeforeObjects; Exit; end;
        if Dataset = 'pcb' then
        begin
            P.Add(JSONPairStr('objects', BeforeObjects, False));
            P.Add(JSONPairStr('schematic_objects', '[]', False));
            AddJSONProperty(P, 'schematic_inventory_status', 'not_requested');
        end
        else
        begin
            P.Add(JSONPairStr('objects', '[]', False));
            P.Add(JSONPairStr('schematic_objects', BeforeObjects, False));
            AddJSONProperty(P, 'pcb_inventory_status', 'not_requested');
        end;
        Query := TStringList.Create;
        try
            AddJSONProperty(Query, 'dataset', Dataset); AddJSONInteger(Query, 'offset', Offset);
            AddJSONInteger(Query, 'limit', Limit); AddJSONProperty(Query, 'kind', Kind);
            AddJSONProperty(Query, 'component', ComponentName); P.Add(JSONPairStr('query', BuildJSONObject(Query), False));
        finally Query.Free; end;
        AddJSONInteger(P, 'dataset_total_count', TotalBefore);
        AddJSONBoolean(P, 'pcb_inventory_complete', (Dataset = 'pcb') and (Kind = 'all') and
            (ComponentName = '') and (Offset = 0) and (TotalBefore <= Limit));
        AddJSONProperty(P, 'dirty_state', BridgeProjectDirtyState(0));
        AddJSONInteger(P, 'origin_x_coord', Board.XOrigin); AddJSONInteger(P, 'origin_y_coord', Board.YOrigin);
        AddJSONProperty(P, 'native_length_unit', 'coord'); AddJSONInteger(P, 'coord_per_mil', MilsToCoord(1));
        BridgeMissing(P, 'stackup', 'Not requested in a geometry page');
        AddJSONProperty(P, 'compiled_connectivity_status', 'not_checked');
        AddJSONProperty(P, 'compiled_connectivity_reason', 'No implicit compilation');
        PilotTrace('snapshot_page_second_pass_begin');
        if Dataset = 'pcb' then AfterObjects := BridgeBoardObjects(Offset, Limit, Kind, ComponentName, TotalAfter)
        else AfterObjects := BridgeSchematicObjects(Offset, Limit, TotalAfter);
        if (BeforeObjects = AfterObjects) and (TotalBefore = TotalAfter) then
            AddJSONProperty(P, 'page_coherence', 'verified')
        else AddJSONProperty(P, 'page_coherence', 'mixed');
        if Dataset = 'pcb' then
        begin
            if (BeforeObjects = AfterObjects) and (TotalBefore = TotalAfter) then
                AddJSONProperty(P, 'pcb_coherence', 'verified')
            else AddJSONProperty(P, 'pcb_coherence', 'mixed');
        end
        else AddJSONProperty(P, 'pcb_coherence', 'not_checked');
        AddJSONProperty(P, 'whole_project_coherence', 'not_verified');
        Result := BuildJSONObject(P);
        PilotTrace('snapshot_complete');
    finally P.Free; end;
end;

function BridgeFindObject(Address: String): IPCB_Primitive;
var Board: IPCB_Board; It: IPCB_BoardIterator; Prim: IPCB_Primitive;
begin
    Result := nil; Board := GetBoardSafe(0); It := Board.BoardIterator_Create;
    try
        It.AddFilter_ObjectSet(AllObjects); It.AddFilter_LayerSet(AllLayers); It.AddFilter_Method(eProcessAll);
        Prim := It.FirstPCBObject;
        while Prim <> nil do
        begin
            if IntToStr(Prim.I_ObjectAddress) = Address then begin Result := Prim; Exit; end;
            Prim := It.NextPCBObject;
        end;
    finally Board.BoardIterator_Destroy(It); end;
end;

function BridgeMeasure(Arguments: TStringList): String;
var A, B: IPCB_Primitive; Board: IPCB_Board; P: TStringList; DX, DY, D: Double;
begin
    A := BridgeFindObject(Arguments.Values['a']); B := BridgeFindObject(Arguments.Values['b']);
    if (A = nil) or (B = nil) then begin Result := 'ERROR: OBJECT_NOT_FOUND'; Exit; end;
    Board := GetBoardSafe(0); P := TStringList.Create;
    try
        if Arguments.Values['metric'] = 'pad_center_distance' then
        begin
            if (A.ObjectId <> ePadObject) or (B.ObjectId <> ePadObject) then begin Result := 'ERROR: PAD_OBJECTS_REQUIRED'; Exit; end;
            DX := A.x - B.x; DY := A.y - B.y; D := Sqrt(DX * DX + DY * DY);
        end
        else
        begin
            if (Layer2String(A.Layer) <> Arguments.Values['layer']) or (Layer2String(B.Layer) <> Arguments.Values['layer']) then
            begin Result := 'ERROR: LAYER_SPECIFIC_GEOMETRY_REQUIRED'; Exit; end;
            D := Board.PrimPrimDistance(A, B);
        end;
        AddJSONProperty(P, 'metric', Arguments.Values['metric']); AddJSONNumber(P, 'value_mm', D / MilsToCoord(1) * 0.0254);
        AddJSONProperty(P, 'a', Arguments.Values['a']); AddJSONProperty(P, 'b', Arguments.Values['b']);
        AddJSONProperty(P, 'layer', Arguments.Values['layer']); AddJSONProperty(P, 'method', 'native_geometry');
        Result := BuildJSONObject(P);
    finally P.Free; end;
end;

function BridgeMessagesPage(Offset, Limit: Integer): String;
var Manager: IMessagesManager; Item: IMessageItem; Project: IProject; Rows, P, ResultProps: TStringList;
    I, Last, Total, ForeignCount, UnattributedCount: Integer;
    DocumentPath, Attribution, ProjectPath: String; IncludeText: Boolean;
begin
    Manager := GetWorkspace.DM_MessagesManager;
    if Manager = nil then begin Result := 'ERROR: MESSAGE_MANAGER_UNAVAILABLE'; Exit; end;
    Total := Manager.MessagesCount;
    if Offset > Total then begin Result := 'ERROR: MESSAGE_OFFSET_OUT_OF_RANGE'; Exit; end;
    Last := Offset + Limit; if Last > Total then Last := Total;
    Project := PilotReadProject(0); ProjectPath := Project.DM_ProjectFullPath;
    ForeignCount := 0; UnattributedCount := 0;
    Rows := TStringList.Create; ResultProps := TStringList.Create;
    try
        for I := Offset to Last - 1 do
        begin
            Item := Manager.Messages(I); DocumentPath := Item.Document;
            Attribution := 'unattributed'; IncludeText := False;
            if ((Length(DocumentPath) > 2) and (Copy(DocumentPath, 2, 1) = ':')) or
               (Copy(DocumentPath, 1, 2) = '\\') then
            begin
                if PilotAllowedDocument(DocumentPath) or
                   (LowerCase(ExpandFileName(DocumentPath)) = LowerCase(ExpandFileName(ProjectPath))) then
                begin Attribution := 'exact_project_path'; IncludeText := True; end
                else begin Attribution := 'outside_selected_project'; ForeignCount := ForeignCount + 1; end;
            end
            else if (DocumentPath <> '') and (ExtractFileName(DocumentPath) = DocumentPath) and
                    (PilotAllowedDocument(BridgeCurrentRoot(0) + '\' + DocumentPath) or
                     (LowerCase(DocumentPath) = LowerCase(ExtractFileName(ProjectPath)))) then
            begin Attribution := 'ambiguous_basename'; IncludeText := True; end;
            if Attribution = 'unattributed' then UnattributedCount := UnattributedCount + 1;
            P := TStringList.Create;
            try
                AddJSONInteger(P, 'panel_index', I); AddJSONProperty(P, 'document', DocumentPath);
                AddJSONProperty(P, 'attribution', Attribution);
                if IncludeText then
                begin
                    AddJSONProperty(P, 'text', Item.Text); AddJSONProperty(P, 'message_class', Item.MsgClass);
                    AddJSONProperty(P, 'source', Item.Source); AddJSONInteger(P, 'image_index', Item.ImageIndex);
                    AddJSONNumber(P, 'message_datetime_delphi_days', Item.MsgDateTime);
                end
                else BridgeMissing(P, 'text', 'Message ownership is not established for the selected project');
                Rows.Add(BuildJSONObject(P));
            finally P.Free; end;
        end;
        if Manager.MessagesCount <> Total then begin Result := 'ERROR: MESSAGES_CHANGED_DURING_READ'; Exit; end;
        AddJSONInteger(ResultProps, 'panel_total_count', Total);
        AddJSONInteger(ResultProps, 'offset', Offset); AddJSONInteger(ResultProps, 'scanned_count', Last - Offset);
        AddJSONInteger(ResultProps, 'outside_project_count', ForeignCount);
        AddJSONInteger(ResultProps, 'unattributed_count', UnattributedCount);
        ResultProps.Add(JSONPairStr('records', BuildJSONArray(Rows), False));
        Result := BuildJSONObject(ResultProps);
    finally ResultProps.Free; Rows.Free; end;
end;

function BridgeReadMessages(Arguments: TStringList): String;
var Offset, Limit: Integer; First, Second: String;
begin
    Offset := StrToInt(Arguments.Values['offset']); Limit := StrToInt(Arguments.Values['limit']);
    if (Offset < 0) or (Offset > 1000000) or (Limit < 1) or (Limit > 100) then
    begin Result := 'ERROR: INVALID_MESSAGE_PAGE'; Exit; end;
    First := BridgeMessagesPage(Offset, Limit);
    if Pos('ERROR:', First) = 1 then begin Result := First; Exit; end;
    Second := BridgeMessagesPage(Offset, Limit);
    if First <> Second then begin Result := 'ERROR: MESSAGES_CHANGED_DURING_READ'; Exit; end;
    Result := First;
end;

function BridgeControlledChange(CommandName: String; Arguments: TStringList): String;
begin
    Result := 'ERROR: NATIVE_WRITE_ACCEPTANCE_REQUIRED';
end;
