module dff_sync
#(
    parameter int   pSYNC_STAGES,
        // NOTE: minimum 1
    parameter logic pSYNC_DEFAULT = 1'b0
)
(
    // ------ 'clk' synchronous ------
    input  logic clk,
    input  logic srst,
    output logic sync = pSYNC_DEFAULT,

    // ------ asynchronous ------
    input  logic async
);

    // ----------------------------------------------
    //  Internal signals
    // ----------------------------------------------

    logic [pSYNC_STAGES-1:0] i_sync_stages = {(pSYNC_STAGES){pSYNC_DEFAULT}};


    // ----------------------------------------------
    //  Synchronization
    // ----------------------------------------------

    always@(posedge clk) begin : SyncStage
        if (srst == 1'b1) begin
            i_sync_stages   <= {(pSYNC_STAGES){pSYNC_DEFAULT}};
            sync            <= pSYNC_DEFAULT;

        end else begin
            i_sync_stages       <= i_sync_stages << 1;
            i_sync_stages[0]    <= async;

            sync                <= i_sync_stages[$bits(i_sync_stages)-1];
        end
    end : SyncStage

endmodule : dff_sync