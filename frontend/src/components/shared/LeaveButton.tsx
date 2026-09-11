import Button from "@/components/ui/Button";
import { FaUser } from 'react-icons/fa';
import { FaDoorOpen } from 'react-icons/fa6';
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
      <Button 
        variant="ghost" size="sm" 
        className="flex gap-2 items-center"
        onClick={handleLeave}
        onMouseEnter={()=>setHovered(true)}
        onMouseLeave={()=>setHovered(false)}
      >
         { hovered ? 
            <><FaDoorOpen /><span>Выйти</span></> : 
            <><FaUser /><span>{username}</span></> 
         }
      </Button>
    );
}
