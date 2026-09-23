{..............................................................................}
{ McpListener.pas - persistent in-Altium listener for the MCP bridge.          }
{                                                                              }
{ Why this exists: the command-line dispatch                                   }
{   X2.EXE -RScriptingSystem:RunScript(ProjectName="..."|ProcName="...")       }
{ does not attach to an Altium instance the user started themselves. Measured  }
{ 2026-09-22: it cold-started a SECOND instance (+0.5s, title "Home Page",     }
{ then "No License"), the request never reached the running instance, and      }
{ Altium's licensing docs state each instance holds its own seat. So the       }
{ request has to be picked up by a script already inside the user's instance.  }
{                                                                              }
{ Mechanism: a TTimer on a non-modal form. StartMcpListener arms the timer and }
{ RETURNS - that is the point, the scripting engine stays free between ticks.  }
{ A blocking While/Sleep loop would freeze Altium instead.                     }
{                                                                              }
{ NO STATE OUTSIDE THE FORM'S OWN CONTROLS. The first version kept             }
{ ListenerActive / PumpInTick / RequestsServed / StartedTick as unit-level     }
{ variables. Measured 2026-09-22: by the time a later call ran they read back  }
{ as zero - a heartbeat written from StopListener reported uptime_ms 5013906   }
{ (~83 min) for a listener up less than two minutes, i.e. StartedTick was 0,   }
{ not the value StartMcpListener had just assigned. The first tick therefore   }
{ saw ListenerActive = False and switched the timer off. Only two primitives   }
{ are used for state now, both already proven in this project's working        }
{ scripts: a control's Caption, and the timer's Enabled. Component .Tag is     }
{ NOT used - nothing here has demonstrated that it works in this engine.       }
{                                                                              }
{ Other constraints this file is built around (all of them bite silently):     }
{   - The timer only ticks while the form is VISIBLE. Hiding it suspends the   }
{     listener, so the form stays up for as long as the listener runs.         }
{   - A DFM event handler resolves only inside the unit that owns the form,    }
{     so every handler below lives here, not in Altium_API.pas.                }
{   - DelphiScript has no forward declarations: a procedure must appear above  }
{     its callers. DFM handlers bind by name anywhere in this unit.            }
{   - A modal dialog raised during a tick blocks Altium's UI thread and stalls }
{     the timer until somebody clicks OK. Nothing here shows one; failures go  }
{     into the response file that the caller is already waiting on.            }
{..............................................................................}

const
    // Same exchange directory Altium_API.pas resolves in InitializeFilePaths.
    // Repeated as a literal rather than read across units, because the working
    // code in this project passes ROOT_DIR into other units as a parameter and
    // never reads another unit's globals.
    LISTENER_ROOT = 'C:\Users\Public\altium_mcp\';

    // lbl_State.Caption doubles as the only surviving flag: it shows the user
    // what the pump is doing AND tells the next tick whether one is already in
    // flight.
    STATE_IDLE    = 'Listening';
    STATE_BUSY    = 'Busy - running a command';
    STATE_STOPPED = 'Stopped';

{..............................................................................}
{ Startup tracing to C:\Users\Public\altium_mcp\listener_trace.log.            }
{                                                                              }
{ Kept deliberately, not leftover scaffolding. Failures in this environment    }
{ are silent by construction: this unit must not raise dialogs (they freeze    }
{ Altium's UI thread and stall the pump), and a DelphiScript error leaves the  }
{ script paused in the debugger with nothing on screen. During bring-up the    }
{ listener twice reported a plausible-looking window while the pump was dead,  }
{ and this log is what distinguished "never entered" from "ran to the end".    }
{ It appends a handful of lines per start, not per tick.                       }
{..............................................................................}
procedure McpTrace(Msg: String);
var
    Log : TStringList;
    Path: String;
begin
    try
        Path := LISTENER_ROOT + 'listener_trace.log';
        Log := TStringList.Create;
        try
            if FileExists(Path) then
                Log.LoadFromFile(Path);
            Log.Add(Msg);
            Log.SaveToFile(Path);
        finally
            Log.Free;
        end;
    except
    end;
end;

{..............................................................................}
{ Heartbeat. The Python side reads this file's freshness to tell "the listener }
{ is running" from "nobody is home", so it can fail with a useful message      }
{ instead of waiting out its 120 s response timeout.                           }
{                                                                              }
{ Written on every tick rather than on a schedule of its own: tracking "when   }
{ did I last write" needs a surviving counter, which is exactly what this      }
{ engine does not give us. Two 25-byte writes a second is the cheaper problem. }
{..............................................................................}
procedure WriteHeartbeat(Alive: Boolean);
var
    Beat : TStringList;
begin
    Beat := TStringList.Create;
    try
        if Alive then
            Beat.Text := '{"alive": true}'
        else
            Beat.Text := '{"alive": false}';
        Beat.SaveToFile(LISTENER_ROOT + 'listener.json');
    finally
        Beat.Free;
    end;
end;

{..............................................................................}
{ Stop the pump and record the shutdown, so a caller polling the heartbeat     }
{ sees "stopped" instead of waiting for a timeout.                             }
{..............................................................................}
procedure StopListener;
begin
    try
        tmr_Poll.Enabled := False;
    except
    end;
    try
        WriteHeartbeat(False);
    except
    end;
    try
        lbl_State.Caption := STATE_STOPPED;
    except
    end;
end;

{..............................................................................}
{ One poll tick.                                                               }
{..............................................................................}
procedure tmr_PollTimer(Sender: TObject);
begin
    // Re-entrancy guard. This tick does not pump messages itself, but the
    // Altium calls underneath ProcessPendingRequest may, and a second tick
    // arriving mid-command would pick up the NEXT request while the first is
    // still in flight.
    if lbl_State.Caption = STATE_BUSY then
        Exit;

    try
        // Altium is shutting down - stop touching its object model.
        try
            if Client.IsQuitting then
            begin
                tmr_Poll.Enabled := False;
                Exit;
            end;
        except
        end;

        // Written first, so liveness does not depend on how the command below
        // turns out: a tick that reaches this point proves the pump is running.
        WriteHeartbeat(True);

        lbl_State.Caption := STATE_BUSY;
        try
            ProcessPendingRequest;
        finally
            lbl_State.Caption := STATE_IDLE;
        end;
    except
        // A failing tick must not kill the pump: the next request may be fine.
        // ProcessPendingRequest has already written whatever error it could
        // into the response file.
        try
            lbl_State.Caption := STATE_IDLE;
        except
        end;
    end;
end;

procedure btn_StopClick(Sender: TObject);
begin
    StopListener;
    McpListenerForm.Close;
end;

{..............................................................................}
{ Entry point. Parameterless so it is offered in File > Run Script.            }
{..............................................................................}
procedure StartMcpListener;
begin
    McpTrace('--- StartMcpListener entered');

    if tmr_Poll.Enabled then
        McpTrace('guard: tmr_Poll.Enabled = TRUE (will show and exit)')
    else
        McpTrace('guard: tmr_Poll.Enabled = FALSE (will start)');

    McpTrace('caption now: [' + lbl_State.Caption + ']');

    // Guard on the timer's own state rather than a flag of our own: component
    // properties are the only state that survives to the next call here.
    if tmr_Poll.Enabled then
    begin
        McpListenerForm.Show;
        Exit;
    end;

    if not DirectoryExists(LISTENER_ROOT) then
        ForceDirectories(LISTENER_ROOT);
    McpTrace('step 1: directory ok');

    WriteHeartbeat(True);
    McpTrace('step 2: heartbeat written');

    McpListenerForm.Show;
    McpTrace('step 3: form shown');

    lbl_State.Caption := STATE_IDLE;
    McpTrace('step 4: caption set to [' + lbl_State.Caption + ']');

    tmr_Poll.Enabled := True;
    McpTrace('step 5: timer enabled, Enabled now = ' + BoolToStr(tmr_Poll.Enabled, True));
    // Returning here is deliberate: the engine stays free and the timer drives
    // every later request.
end;

{ McpListenerFormClose sits at the end because it calls StopListener, and      }
{ DelphiScript resolves calls textually. Closing the window must stop the pump }
{ - a hidden form's timer stops ticking anyway, and a listener that looks      }
{ alive in the heartbeat but never answers is the worst outcome.               }
procedure McpListenerFormClose(Sender: TObject; var Action: TCloseAction);
begin
    StopListener;
end;
