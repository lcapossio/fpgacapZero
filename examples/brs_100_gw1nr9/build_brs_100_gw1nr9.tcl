if {$argc < 1} {
    error "Expecting -tclargs <repo path>"
}

set repo_path           [lindex $argv 0]

set project_name        "proj"
set target_part_number  "GW1NR-LV9QN88PC7/I6"
set target_part_version "C"

set examples_dir        "examples"
set brs_100_gw1nr9_dir  "brs_100_gw1nr9"
set build_dir           "out"

set this_path            "${repo_path}/${examples_dir}/${brs_100_gw1nr9_dir}"

if {[file isdirectory $build_dir]} {
    puts "Cleanup previous build"
    file delete -force $build_dir
}

puts "Creating Gowin EDA project, specs:"
puts "\tTarget part number: ${target_part_number}"
puts "\tTarget part version: ${target_part_version}"
create_project -name $project_name -dir $build_dir -pn $target_part_number -device_version $target_part_version -force

set_option -verilog_std sysv2017
set_option -vhdl_std vhd2008
set_option -use_sspi_as_gpio 1
set_option -use_mspi_as_gpio 1
set_option -place_option 2
set_option -replicate_resources 1
set_option -clock_route_order 1
set_option -route_option 1

set verilog_files [list \
    $repo_path/rtl/fcapz_version.vh \
    $repo_path/rtl/reset_sync.v \
    $repo_path/rtl/dpram.v \
    $repo_path/rtl/trig_compare.v \
    $repo_path/rtl/fcapz_regbus_mux.v \
    $repo_path/rtl/fcapz_ela.v \
    $repo_path/rtl/fcapz_ela_gowin.v \
    $repo_path/rtl/jtag_reg_iface.v \
    $repo_path/rtl/jtag_pipe_iface.v \
    $repo_path/rtl/jtag_burst_read.v \
    $repo_path/rtl/jtag_tap/jtag_tap_gowin.v \
    $repo_path/rtl/fcapz_async_fifo.v \
    $repo_path/rtl/fcapz_ejtagaxi.v \
    $repo_path/rtl/fcapz_eio.v \
    $repo_path/rtl/fcapz_eio_gowin.v \
    \
    $repo_path/rtl/gowin/gw_jtag.v \
    \
    $this_path/brs_100_gw1nr9_top.v
]

foreach src $verilog_files {
    add_file -type verilog $src
}

add_file "${this_path}/brs_100_gw1nr9_loc.cst"
add_file "${this_path}/brs_100_gw1nr9_timing.sdc"

set_option -top_module brs_100_gw1nr9_top

puts "Launching Synthesis"
run syn

puts "Synthesis Complete"

puts "Launching Place-and-Route"
run pnr

puts "Deploying Bitstream"
file copy -force impl/pnr/${project_name}.fs ${this_path}/${build_dir}/fcapz_brs_100_gw1nr9.fs
