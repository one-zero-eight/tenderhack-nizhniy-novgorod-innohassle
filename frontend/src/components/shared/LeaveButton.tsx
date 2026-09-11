import Button from "@/components/ui/Button";
import { getUsername, clearUsername } from "@/lib/storage";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";


export default function LeaveButton() {
    const navigate = useNavigate();
    const handleLeave = () => {
        clearUsername()
        navigate({ to: '/auth' })
    };

    const username = getUsername();
    const [hovered, setHovered] = useState(false);


    return (
      <Button variant="ghost" size="sm" 
        onClick={handleLeave}
        onMouseEnter={()=>setHovered(true)}
        onMouseLeave={()=>setHovered(false)}
      >
        { hovered ?  "Выйти" : username }
      </Button>
    );
}
