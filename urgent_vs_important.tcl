#############################################################################
# Generated by PAGE version 6.2
#  in conjunction with Tcl version 8.6
#  Aug 21, 2021 06:25:56 PM -05  platform: Darwin
set vTcl(timestamp) ""
if {![info exists vTcl(borrow)]} {
    tk_messageBox -title Error -message  "You must open project files from within PAGE."
    exit}


if {!$vTcl(borrow) && !$vTcl(template)} {

set vTcl(actual_gui_font_dft_desc)  TkDefaultFont
set vTcl(actual_gui_font_dft_name)  TkDefaultFont
set vTcl(actual_gui_font_text_desc)  TkTextFont
set vTcl(actual_gui_font_text_name)  TkTextFont
set vTcl(actual_gui_font_fixed_desc)  TkFixedFont
set vTcl(actual_gui_font_fixed_name)  TkFixedFont
set vTcl(actual_gui_font_menu_desc)  TkMenuFont
set vTcl(actual_gui_font_menu_name)  TkMenuFont
set vTcl(actual_gui_font_tooltip_desc)  TkDefaultFont
set vTcl(actual_gui_font_tooltip_name)  TkDefaultFont
set vTcl(actual_gui_font_treeview_desc)  TkDefaultFont
set vTcl(actual_gui_font_treeview_name)  TkDefaultFont
set vTcl(actual_gui_bg) #d9d9d9
set vTcl(actual_gui_fg) #000000
set vTcl(actual_gui_analog) #ececec
set vTcl(actual_gui_menu_analog) #ececec
set vTcl(actual_gui_menu_bg) #d9d9d9
set vTcl(actual_gui_menu_fg) #000000
set vTcl(complement_color) #d9d9d9
set vTcl(analog_color_p) #d9d9d9
set vTcl(analog_color_m) #ececec
set vTcl(active_fg) #000000
set vTcl(actual_gui_menu_active_bg)  #ececec
set vTcl(actual_gui_menu_active_fg)  #000000
set vTcl(pr,autoalias) 1
set vTcl(pr,relative_placement) 1
set vTcl(mode) Relative
}




proc vTclWindow.top44 {base} {
    global vTcl
    if {$base == ""} {
        set base .top44
    }
    if {[winfo exists $base]} {
        wm deiconify $base; return
    }
    set top $base
    ###################
    # CREATING WIDGETS
    ###################
    vTcl::widgets::core::toplevel::createCmd $top -class Toplevel \
        -background $vTcl(actual_gui_bg) 
    wm focusmodel $top passive
    wm geometry $top 795x653+302+99
    update
    # set in toplevel.wgt.
    global vTcl
    global img_list
    set vTcl(save,dflt,origin) 0
    wm maxsize $top 1399 847
    wm minsize $top 72 15
    wm overrideredirect $top 0
    wm resizable $top 1 1
    wm deiconify $top
    wm title $top "Prioritize!"
    vTcl:DefineAlias "$top" "Toplevel1" vTcl:Toplevel:WidgetProc "" 1
    set vTcl(real_top) {}
    vTcl:withBusyCursor {
    ttk::style configure TSizegrip -background $vTcl(actual_gui_bg)
    vTcl::widgets::ttk::sizegrip::CreateCmd $top.tSi45
    vTcl:DefineAlias "$top.tSi45" "TSizegrip1" vTcl:WidgetProc "Toplevel1" 1
    canvas $top.can46 \
        -background $vTcl(actual_gui_bg) -borderwidth 2 -closeenough 1.0 \
        -height 642 -insertbackground black -relief ridge \
        -selectbackground blue -selectforeground white -width 551 
    vTcl:DefineAlias "$top.can46" "Canvas1" vTcl:WidgetProc "Toplevel1" 1
    set site_3_0 $top.can46
    ttk::separator $site_3_0.tSe48
    vTcl:DefineAlias "$site_3_0.tSe48" "TSeparator1" vTcl:WidgetProc "Toplevel1" 1
    ttk::separator $site_3_0.tSe49 \
        -orient vertical 
    vTcl:DefineAlias "$site_3_0.tSe49" "TSeparator2" vTcl:WidgetProc "Toplevel1" 1
    place $site_3_0.tSe48 \
        -in $site_3_0 -x 0 -relx 0.02 -y 0 -rely 0.514 -width 0 \
        -relwidth 0.959 -height 0 -relheight 0.002 -anchor nw \
        -bordermode ignore 
    place $site_3_0.tSe49 \
        -in $site_3_0 -x 0 -relx 0.509 -y 0 -rely 0.016 -width 0 \
        -relwidth 0.002 -height 0 -relheight 0.981 -anchor nw \
        -bordermode ignore 
    ttk::style configure Treeview \
         -font  "$vTcl(actual_gui_font_treeview_desc)"
    vTcl::widgets::ttk::scrolledtreeview::CreateCmd $top.scr47 \
        -background $vTcl(actual_gui_bg) -height 640 \
        -highlightbackground $vTcl(actual_gui_bg) -highlightcolor black \
        -width 230 
    vTcl:DefineAlias "$top.scr47" "Scrolledtreeview1" vTcl:WidgetProc "Toplevel1" 1

    .top44.scr47.01 configure -columns Col1 \
        -height 4
        .top44.scr47.01 configure -columns {Col1}
        .top44.scr47.01 heading #0 -text {Tree}
        .top44.scr47.01 heading #0 -anchor center
        .top44.scr47.01 column #0 -width 110
        .top44.scr47.01 column #0 -minwidth 20
        .top44.scr47.01 column #0 -stretch 1
        .top44.scr47.01 column #0 -anchor w
        .top44.scr47.01 heading Col1 -text {Col1}
        .top44.scr47.01 heading Col1 -anchor center
        .top44.scr47.01 column Col1 -width 110
        .top44.scr47.01 column Col1 -minwidth 20
        .top44.scr47.01 column Col1 -stretch 1
        .top44.scr47.01 column Col1 -anchor w
    ###################
    # SETTING GEOMETRY
    ###################
    place $top.tSi45 \
        -in $top -x 0 -relx 1 -y 0 -rely 1 -anchor se -bordermode inside 
    place $top.can46 \
        -in $top -x 0 -relx 0.299 -y 0 -rely 0.006 -width 0 -relwidth 0.693 \
        -height 0 -relheight 0.983 -anchor nw -bordermode ignore 
    place $top.scr47 \
        -in $top -x 0 -relx 0.008 -y 0 -rely 0.006 -width 0 -relwidth 0.289 \
        -height 0 -relheight 0.98 -anchor nw -bordermode ignore 
    } ;# end vTcl:withBusyCursor 

    vTcl:FireEvent $base <<Ready>>
}



set btop ""
if {$vTcl(borrow)} {
    set btop .bor[expr int([expr rand() * 100])]
    while {[lsearch $btop $vTcl(tops)] != -1} {
        set btop .bor[expr int([expr rand() * 100])]
    }
}
set vTcl(btop) $btop
Window show .
Window show .top44 $btop
if {$vTcl(borrow)} {
    $btop configure -background plum
}

