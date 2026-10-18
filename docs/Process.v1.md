<pre class="mermaid">
flowchart
    subgraph Local
        Start@{ shape: circle, label: "fa:fa-clock 7am" }
        End@{ shape: dbl-circ }    
        RingRequest@{ shape: lean-l, label: "GET clips from Ring API" }
        QWEN@{ shape: bow-rect, label: "Generate highlight reel and caption" }
        ResponseLogic@{ shape: diamond, label: "User decision" }
        Delete@{ shape: rect, label: "Delete ring downloads and reel" }
        Example@{ shape: lin-cyl, label: "Store original clips and finalised reel as examples" }
    end 
    subgraph Ring
        RingExt@{ shape: rect, label: "Ring API" }
    end
    subgraph Docker
        OpenClawWhatsApp@{ shape: rect, label: "OpenClaw: WhatsApp" }
    end
    subgraph WhatsApp
        WhatsAppExt@{ shape: rect, label: "WhatsApp" }
    end          
    Start --> RingRequest
    RingRequest --> RingExt
    RingExt --> QWEN
    QWEN --  Send  reel and caption to WhatsApp  --> OpenClawWhatsApp
    OpenClawWhatsApp <-->  WhatsAppExt
    OpenClawWhatsApp --  User feedback on reel  --> ResponseLogic
    ResponseLogic -- Rejected --> Delete
    ResponseLogic -- Feedback given --> Example
    ResponseLogic -- Accepted --> Example
    Example --> End
    Delete --> End
</pre>