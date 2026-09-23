object McpListenerForm: TMcpListenerForm
  Left = 300
  Top = 200
  BorderStyle = bsSingle
  BorderIcons = [biSystemMenu]
  Caption = 'Altium MCP Listener'
  ClientHeight = 118
  ClientWidth = 330
  Color = clBtnFace
  Font.Charset = DEFAULT_CHARSET
  Font.Color = clWindowText
  Font.Height = -11
  Font.Name = 'Segoe UI'
  Font.Style = []
  OldCreateOrder = False
  Position = poScreenCenter
  PixelsPerInch = 96
  TextHeight = 13
  OnClose = McpListenerFormClose
  object lbl_State: TLabel
    Left = 16
    Top = 14
    Width = 298
    Height = 20
    AutoSize = False
    Caption = 'Not started'
    Font.Charset = DEFAULT_CHARSET
    Font.Color = clWindowText
    Font.Height = -13
    Font.Name = 'Segoe UI'
    Font.Style = [fsBold]
    ParentFont = False
  end
  object lbl_Detail: TLabel
    Left = 16
    Top = 38
    Width = 298
    Height = 34
    AutoSize = False
    Caption = 'Keep this window open. The poll timer only runs while it is visible.'
    WordWrap = True
  end
  object btn_Stop: TButton
    Left = 232
    Top = 82
    Width = 82
    Height = 25
    Caption = 'Stop'
    TabOrder = 0
    OnClick = btn_StopClick
  end
  object tmr_Poll: TTimer
    Enabled = False
    Interval = 500
    OnTimer = tmr_PollTimer
    Left = 16
    Top = 82
  end
end
