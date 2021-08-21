#############################################################################
# Generated by PAGE version 6.2
#  in conjunction with Tcl version 8.6
#  Aug 21, 2021 06:05:53 PM -05  platform: Darwin
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
        -background $vTcl(actual_gui_bg) \
        -highlightbackground $vTcl(actual_gui_bg) -highlightcolor black 
    wm focusmodel $top passive
    wm geometry $top 613x467+319+112
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
    ttk::style configure TFrame -background $vTcl(actual_gui_bg)
    ttk::frame $top.tFr45 \
        -borderwidth 2 -relief groove -width 595 -height 445 
    vTcl:DefineAlias "$top.tFr45" "TFrame1" vTcl:WidgetProc "Toplevel1" 1
    set site_3_0 $top.tFr45
    ttk::style configure Treeview \
         -font  "$vTcl(actual_gui_font_treeview_desc)"
    vTcl::widgets::ttk::scrolledtreeview::CreateCmd $site_3_0.scr45 \
        -background $vTcl(actual_gui_bg) -height 15 \
        -highlightbackground $vTcl(actual_gui_bg) -highlightcolor black \
        -width 30 
    vTcl:DefineAlias "$site_3_0.scr45" "Scrolledtreeview1" vTcl:WidgetProc "Toplevel1" 1

    .top44.tFr45.scr45.01 configure -columns Col1 \
        -height 4
        .top44.tFr45.scr45.01 configure -columns {Col1}
        .top44.tFr45.scr45.01 heading #0 -text {Tree}
        .top44.tFr45.scr45.01 heading #0 -anchor center
        .top44.tFr45.scr45.01 column #0 -width 205
        .top44.tFr45.scr45.01 column #0 -minwidth 20
        .top44.tFr45.scr45.01 column #0 -stretch 1
        .top44.tFr45.scr45.01 column #0 -anchor w
        .top44.tFr45.scr45.01 heading Col1 -text {Col1}
        .top44.tFr45.scr45.01 heading Col1 -anchor center
        .top44.tFr45.scr45.01 column Col1 -width 205
        .top44.tFr45.scr45.01 column Col1 -minwidth 20
        .top44.tFr45.scr45.01 column Col1 -stretch 1
        .top44.tFr45.scr45.01 column Col1 -anchor w
    place $site_3_0.scr45 \
        -in $site_3_0 -x 0 -relx 0.003 -y 0 -width 0 -relwidth 0.699 \
        -height 0 -relheight 0.218 -anchor nw -bordermode ignore 
    ###################
    # SETTING GEOMETRY
    ###################
    place $top.tFr45 \
        -in $top -x 0 -relx 0.01 -y 0 -rely 0.011 -width 0 -relwidth 0.98 \
        -height 0 -relheight 0.981 -anchor nw -bordermode ignore 
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
